# API Contract — beachcomber-be

給 `beachcomber-fe` 串接用。**所有範例都是實際打過的真實回傳，不是示意。**

---

## TL;DR 給趕時間的人

1. **三支 API**：追問拿 `questions[]`（第二節）、Prototype 拿一個網址字串（第二之二節）、Spec 拿四份 Markdown（第二之三節）
2. 前端**不用改任何 code** —— `postMeetingTranscript(id, { text })`、`generatePrototype(id, { text })`、`generateMeetingSpecs(id, { roles })` 全都直接可用
3. 唯一必要改動：`next.config.ts` 加一段 rewrite
4. 回應很慢：追問那支 **10～30 秒**，Prototype 那支 **20～40 秒**，Spec 那支 **1～2 分鐘**，一定要有 loading state
5. **Prototype 那支改走 `/v1/prototypes` 後實測 5/5 成功**（舊路徑 0/5）。仍可能回 `502` —— 前端還是要處理，讓使用者能重按
6. **Spec 那支回的是 `.md` 網址，不是 Markdown 內容** —— `SpecViewer` 正好就是這樣用的
7. `mock-data.ts` 裡 `confidence` / `verdict` / `source` 那些欄位 **Hermes 不會回**

---

## 一、加 rewrite（唯一必要的前端改動）

前端打的是相對路徑 `/api/meetings/...`，不設 rewrite 會打到 Next.js 自己身上變 404。

```ts
// beachcomber-fe/next.config.ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["172.20.10.2"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
```

部署到 Vercel 時設環境變數 `BACKEND_URL` 為 Cloud Run 網址即可，前端程式碼不用動。

> 變數名故意**不加** `NEXT_PUBLIC_` —— rewrite 在 Next.js server 端執行，後端網址不會外洩到瀏覽器，也因此**不需要 CORS**。

---

## 二、POST /api/meetings/{meeting_id}/transcript

送逐字稿，拿回「接下來該追問什麼」。

### Path 參數

| 參數 | 型別 | 說明 |
|---|---|---|
| `meeting_id` | string | 前端產生（現有的 `generateMeetingId()` 就可以）。**後端拿它當對話記憶的 key —— 同一場訪談務必固定用同一個 ID，換 ID 等於開新對話、記憶歸零** |

### Request Body

```json
{ "text": "PM：這次想做一個寄杯券的功能…" }
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `text` | string | **是** | 逐字稿全文（整份送，不是增量） |

**就這一個欄位。** 多送的欄位後端會忽略，不會報錯。

### Response 200

```json
{
  "round": 2,
  "created_at": "2026-09-06T03:41:07.552Z",
  "path": "meetings/2026_09_06_1100_XYZ99/transcript",
  "verified_count": 0,
  "questions": [
    {
      "entry_id": "TKT-001",
      "question": "對於有效期限一年後仍未領取的寄杯券，系統應如何處理其狀態以及其相應的會計處理方式？"
    },
    {
      "entry_id": "TKT-002",
      "question": "店長希望在「每天的營運狀況」中，除了毛利之外，還能看到哪些其他的關鍵指標或數據？"
    }
  ]
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `questions` | `QuestionItem[]` | 最多 5 題，已依重要性排序。**沒有值得追問時會是空陣列 `[]`** —— UI 要處理這個狀態 |
| `questions[].entry_id` | string | 流水號 `TKT-001`、`TKT-002`…。**每次呼叫都從 001 重新編**，不是跨輪唯一 ID。當 React key 可以，別拿來比對「這題是不是上次那題」 |
| `questions[].question` | string | 問題本文 |
| `round` | number | 這場訪談的第幾次呼叫，從 1 開始 |
| `created_at` | string | ISO 8601 UTC，`Z` 結尾 |
| `path` | string | 字串標記而已，後端沒有真的寫檔 |
| `verified_count` | number | **固定 0**，見第六節 |

### 錯誤

| Status | 何時 | Body |
|---|---|---|
| `422` | 少了 `text` 或型別錯 | FastAPI 標準驗證錯誤 |
| `503` | Hermes 忙碌，後端重試 6 次仍擠不進 | `{"detail": "hermes is rate limited, please retry"}` |
| `502` | Hermes 回非 2xx | `{"detail": "hermes returned 500"}` |
| `504` | 連不上／逾時 | `{"detail": "hermes request failed"}` |

**503 仍要處理，但已不是常態。** Hermes 原本只允許 1 個並發，2026-09-06 實測已放寬（同時 4 個請求全部服務）。撞到時仍會回 `429` + `rate_limit_exceeded`，後端自動等 5 秒重試最多 6 次（最長約 30 秒）才放棄。建議顯示「有人正在使用，請稍候」而非報錯。

---

## 二之二、POST /api/meetings/{meeting_id}/prototypes

送同一份逐字稿，Hermes 直接產生一份可操作的 HTML Prototype、上傳到 GCS，回一個公開網址。

**前端不用改 code** —— 現有的 `generatePrototype(meetingId, { text })` 直接可用。

### Request Body

跟第二節完全一樣，只有一個 `text`：

```json
{ "text": "PM：我們要做一個寄杯券功能…" }
```

### Response 200

```json
{
  "prototypes": "https://storage.googleapis.com/research-report-transactions-prototypes-20260905/prototypes/091d3e2f4a5b6c7d8e9f0a1b2c3d4e5f/index.html"
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `prototypes` | string | 公開 HTTPS 網址，可直接塞進 `<iframe>` 或開新分頁。**實測 200 可讀，內容是依逐字稿產的繁中單檔 HTML**（全部 inline，沒有外部資源） |

Prototype 內容規則（Hermes 端強制）：畫面上方固定顯示「此為根據需求訪談建立的討論用 Prototype，不代表所有需求已正式簽核」，未確認的需求會集中在「待確認事項」區塊，示意資料標示為「原型示意資料」，所有互動只在瀏覽器本地模擬。三條都在最近一次實測產出裡驗過。

### 要注意的

> **2026-09-06 變更**：這支改走 Hermes 專用的 `/v1/prototypes`，不再由後端組提示詞叫模型自己跑 `gcloud`。**API 合約沒變，前端不用改。** 變的是可靠度和速度 —— 舊路徑實測 0/5 成功，新路徑 5/5。

1. **半分鐘等級，不再是分鐘等級。** 實測 20～40 秒。逾時設定 `PROTOTYPE_TIMEOUT_SECONDS` 從 600 降到 **180 秒**（仍跟第一支的 120 秒分開）。UI 的 loading state 抓一分鐘就夠。

2. **仍要處理失敗，但已不是常態。** 舊路徑會間歇性回一句 `⚠️ No reply: the model returned empty content…` 而不是網址；新路徑實測 5/5 成功。後端仍保留自動重試一次（`PROTOTYPE_ATTEMPTS`，預設 2），兩次都拿不到網址就回 **502**。

3. **`prototypes` 只要回 200，就一定是 `https://` 開頭的可用網址。** 後端只在 Hermes 給出 `prototype_url` 時才回 200；否則回 502 並在 `detail` 附上 Hermes 實際說了什麼。**不會**把錯誤訊息偽裝成網址塞給你，所以前端不需要自己檢查「這個字串長得像不像網址」。

4. **✅ 網址唯一性問題已解決。** uuid 改由 Hermes server 端產生，實測 10 次全不同、且都是合法 uuid4。**Prototype Archive 存這個字串是安全的**，舊網址會一直指向當初那份。
   （舊路徑是讓模型自己編 uuid，實測拿過 `0123456789abcdef0123456789abcdef` 這種照抄範例的佔位符，同路徑會被靜默覆蓋。）

5. **這支跟對話記憶完全無關。** `/v1/prototypes` 只吃 `transcript`、也不回對話 ID，所以既讀不到前幾輪訪談，也不會影響下一輪追問。（後端仍把逐字稿和產出的網址記在 `meeting_id` 底下給 specs 那支用。）

### 錯誤

| Status | 何時 | 前端該怎麼辦 |
|---|---|---|
| `422` | 少了 `text` | 修 request |
| `502` | Hermes 跑完但沒給出網址（已重試仍失敗）。`detail` 附上它實際回的內容 | **顯示「產生失敗，請再試一次」並讓使用者重按** |
| `503` | Hermes 忙碌，重試耗盡 | 顯示「有人正在使用，請稍候」 |
| `504` | 連不上，或超過 180 秒 | 同上，可讓使用者重試 |

### TypeScript 型別

`lib/api/prototype.ts` 現有宣告即為正解，不用改：

```ts
export type MeetingPrototypeResponse = {
  prototypes: string;
};
```

---

## 二之三、POST /api/meetings/{meeting_id}/specs

依角色產出 spec 文件。**回傳的 `spec` 是 `.md` 檔的公開網址，不是 Markdown 內容** —— 這正是 `SpecViewer` 要的（它拿去做 `<iframe src>` 和「複製 Spec URL」）。

### Request Body

```jsonc
{
  "roles": ["pm", "ui", "eng", "qa"],   // 必填
  "transcript": "完整逐字稿…",            // 選填
  "prototype_url": "https://…"          // 選填
}
```

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `roles` | `("pm"\|"eng"\|"ui"\|"qa")[]` | **是** | 要哪幾份。重複的會去重、順序照給的來。其他值一律 `422` |
| `transcript` | string | 否 | 不給就用後端記憶裡這個 `meeting_id` 的逐字稿。**上限 50,000 字元**，超過回 `422` |
| `prototype_url` | string | 否 | 不給就用後端記得的那份 prototype 網址 |

**前端現在的 `generateMeetingSpecs(meetingId, { roles })` 不用改。** 只送 `roles` 就能動 —— 前面呼叫 transcript 或 prototypes 時，後端已經把逐字稿和 prototype 網址記在同一個 `meeting_id` 底下了。

> 前提一樣是：同一場訪談固定用同一個 `meeting_id`。若那個 meeting 從來沒送過逐字稿、request 又沒帶 `transcript`，會回 `422` 並說明原因。

### Response 200

```json
{
  "response": [
    {
      "role": "pm",
      "spec": "https://storage.googleapis.com/research-report-transactions-prototypes-20260905/specs/b7b8b11802cc4365b52d31a3144db611/pm.md"
    },
    {
      "role": "ui",
      "spec": "https://storage.googleapis.com/research-report-transactions-prototypes-20260905/specs/b7b8b11802cc4365b52d31a3144db611/ui.md"
    }
  ]
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `response` | `{ role, spec }[]` | 順序與 request 的 `roles` 一致（去重後）。`roles: []` 就回 `[]` |
| `response[].spec` | string | **`.md` 檔的公開 HTTPS 網址**，不是內容。可直接 `<iframe src>` 或開新分頁 |

實測四個網址都可讀：pm 7.6 KB、ui 7.8 KB、eng 10.1 KB、qa 8.3 KB，全是繁中 Markdown。

### 要注意的

1. **約 60～70 秒。** 實測端到端 63～68 秒。要有 loading state。

2. **一次呼叫就產齊四份，`roles` 只是過濾。** Hermes 這支不接受角色參數，一律產 `pm`/`ui`/`eng`/`qa` 四份；後端依你給的 `roles` 篩選後回傳。所以**只要一個角色跟要四個角色，成本和耗時完全一樣** —— UI 若打算做「先看 PM、再看 ENG」的分次載入，不如一次要四個然後本地切換。

3. **每次呼叫都是新的 uuid、四個檔在同一個資料夾底下。** 實測三次分別是 `3ccd7de1…`、`a403c18f…`、`b7b8b118…`，各自獨立，網址可以安心存起來當歷史紀錄。Prototype 那支改走 `/v1/prototypes` 後也是一樣（原本會撞路徑）。

4. **這支不寫入對話記憶**，也不走對話端點。它有自己的 `/v1/specs`，跟訪談那條對話線無關。

### 錯誤

| Status | 何時 | 前端該怎麼辦 |
|---|---|---|
| `422` | `roles` 有不認識的值；沒有逐字稿可用；或逐字稿超過 50,000 字元 | 修 request |
| `502` | Hermes 拒絕或沒產出 spec，`detail` 附上原因 | 顯示「產生失敗，請再試一次」 |
| `503` | Hermes 忙碌重試耗盡 | 顯示「有人正在使用，請稍候」 |
| `504` | 連不上或逾時 | 同上 |

### TypeScript 型別

`lib/api/spec.ts` 現有宣告即為正解，不用改：

```ts
export type SpecGenerationRole = "pm" | "eng" | "ui" | "qa";

export type MeetingSpecsItem = {
  role: SpecGenerationRole;
  spec: string;   // 網址，不是 Markdown 內容
};

export type MeetingSpecsResponse = {
  response: MeetingSpecsItem[];
};
```

---

## 三、TypeScript 型別

可直接取代 `lib/api/meetings.ts` 現有宣告：

```ts
export type MeetingTranscriptPayload = {
  text: string;
};

export type MeetingQuestionItem = {
  entry_id: string;
  question: string;
};

export type MeetingTranscriptResponse = {
  round: number;
  created_at: string;
  path: string;
  verified_count: number;
  questions: MeetingQuestionItem[];
};
```

現有宣告 `{ entry_id?: string; question?: string }` 兩個欄位都是選填 —— 後端一定會回，`?` 可以拿掉。

---

## 四、對話記憶（前端不用管，但要知道行為）

前端每次只送 `{ text }`。後端用 `meeting_id` 記住這場訪談問過哪些問題、以及 Hermes 的對話 ID，下一輪自動帶回去，讓 Hermes 知道哪些已經問過。

**前端唯一要做的**：同一場訪談固定用同一個 `meeting_id`。

### 實測結果與限制（請據此設計 UI）

兩輪測試，前端兩次都只送 `{ text }`：

| | 第 1 輪 | 第 2 輪 |
|---|---|---|
| 題數 | 3 | 3 |
| 字面完全相同 | — | 0 題 |
| **語意幾乎相同** | — | **1 題** |

第 2 輪確實會往下追（第 1 輪問「收入何時認列」，第 2 輪逐字稿回答後，改問「逾期未領的會計處理」）。

**但去重不保證。** 實測第 2 輪出現了一題跟第 1 輪幾乎一樣的：

> 第 1 輪：「…門市兌換時的具體操作流程為何？例如門市人員如何核銷，以及是否支援分次兌換或跨店兌換？」
> 第 2 輪：「…門市兌換時的具體操作流程為何？例如門市人員如何核銷、**如何驗證票券**，以及是否支援分次兌換或跨店兌換？」

這不算 Hermes 出錯 —— 提示詞規定的是「已經在逐字稿中**得到明確答案**的問題」才不再問，而那一輪逐字稿裡確實沒人回答兌換流程，所以它繼續追是合規的。

**對 UI 的意涵**：不要假設每輪的問題彼此互斥。如果體驗上不能接受重複卡片，前端需要自己做一層近似比對（例如比對前 15 個字），或讓使用者手動關掉不想看的卡片。

---

## 五、⚠️ 跟 mock-data.ts 對不上的地方

`lib/mock-data.ts` 的 `mockMeetingTranscriptResponse` 裡每筆 question 有這些欄位：

```
trace, confidence, downgraded, verdict, axis, origin,
fact, impact, source_ref, source{title, locator, status}, note
```

**這些 Hermes 一個都不會回。**

不是後端沒轉 —— 是 `api1.md` 定義的提示詞輸出格式本來就只有字串陣列：

```json
{ "questions": ["問題一", "問題二"] }
```

後端不會憑空生成 `confidence`、`source` 這類欄位，那等於捏造資料。

**若 UI 已照 mock 那份刻好，兩條路：**

1. 改 `api1.md` 的提示詞，要求 Hermes 每題輸出結構化物件（含信心等級、依據來源），後端再跟著調 mapping
2. UI 先只用 `entry_id` + `question`，其餘欄位之後再談

這需要決定，不是後端單方面能補的。

---

## 六、別依賴這個值

**`verified_count` 固定是 `0`。** Hermes 沒有任何查證／驗證機制，沒有真實來源可填。UI 不要拿它做判斷或顯示統計。

要真的有「已查證幾則」，得先決定查證是誰做、依據什麼 —— 目前整條鏈裡沒有這個東西。

---

## 七、本機怎麼跑

```bash
cd beachcomber-be
uv sync
uv run uvicorn main:app --reload --port 8000
```

- 健康檢查：http://localhost:8000/health
- **互動式 API 文件**：http://localhost:8000/docs ← 可以直接在網頁上送測試 request，不用寫 code

Hermes 塞住不想等的話，把 `.env` 的 `USE_MOCK_HERMES` 改成 `true`：回固定假資料、不出網路、格式完全一致，前端可以照常開發 UI。

---

## 八、還沒做 / 提醒

第三隻 API（Spec 生成）。前端 `lib/api/session.ts`、`lib/api/spec.ts` 裡那些 `// API TODO` 的 stub 目前仍是本地假回應，沒有對應後端；`restorePrototypeById`（`GET /api/prototypes/:id`）也還沒做 —— 目前 Prototype 網址是永久可讀的，前端自己存字串就能還原，不一定需要這支。

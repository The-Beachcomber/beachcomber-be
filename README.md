# beachcomber-be

`beachcomber-fe` 與 Hermes 之間的橋接後端。收前端的逐字稿，打 Hermes，把回來的東西轉成前端要的形狀 —— 訪談中產「接下來該追問什麼」，訪談後產「可以點的 HTML Prototype」與四份角色 Spec。

**給前端串接的人看這份**：[`docs/api-contract.md`](docs/api-contract.md)

## 跑起來

```bash
uv sync
uv run uvicorn main:app --reload --port 8000
```

- 互動式 API 文件：http://localhost:8000/docs
- 健康檢查：http://localhost:8000/health
- 測試：`uv run pytest`

`.env` 已設好可直接打真的 Hermes。改 `USE_MOCK_HERMES=true` 就回固定假資料、不出網路 —— Hermes 塞住時前端可以照常開發。

## API（三隻）

前兩隻只收一個欄位 `{ text }`，第三隻收 `{ roles }`。三隻都用 `meeting_id` 當同一場訪談的 key。

第三隻的介面與周邊已完成，但**擋在提示詞**（見最後一節）。

## 第一隻：追問問題

`POST /api/meetings/{meeting_id}/transcript`

```jsonc
// Request — 就這一個欄位
{ "text": "逐字稿全文" }
```

```jsonc
// Response
{
  "round": 2,
  "created_at": "2026-09-06T03:41:07.552Z",
  "path": "meetings/2026_09_06_1100_XYZ99/transcript",
  "verified_count": 0,
  "questions": [
    { "entry_id": "TKT-001", "question": "對於有效期限一年後仍未領取的寄杯券…" }
  ]
}
```

錯誤：`422` 少了 `text`／`503` Hermes 忙碌重試耗盡／`502` Hermes 回非 2xx／`504` 連不上。

## 第二隻：產 Prototype

`POST /api/meetings/{meeting_id}/prototypes`

送同一份逐字稿，Hermes 直接寫出一份可操作的單檔 HTML、上傳到 GCS，回一個公開網址。

```jsonc
// Request — 跟第一隻一模一樣
{ "text": "逐字稿全文" }
```

```jsonc
// Response
{
  "prototypes": "https://storage.googleapis.com/research-report-transactions-prototypes-20260905/prototypes/f8e7d6c5b4a3e2d1c0b9a876f5e4d3c2/index.html"
}
```

網址可以直接塞 `<iframe>` 或開新分頁。實測 `GET` 回 200，內容是依逐字稿產的繁中單檔 HTML（CSS/JS/資料全部 inline，零外部資源）。

內容規則由 Hermes 端強制（後端不再自己組提示詞）：頁面上方固定顯示「此為根據需求訪談建立的討論用 Prototype，不代表所有需求已正式簽核」；未確認的需求集中在「待確認事項」區塊；示意資料標示為「原型示意資料」；所有互動只在瀏覽器本地模擬。三條都在最近一次實測產出裡驗過。

錯誤：`422` 少了 `text`／**`502` Hermes 跑完但沒給出網址**（重試後仍失敗，`detail` 附上它實際回了什麼）／`503` Hermes 忙碌重試耗盡／`504` 連不上或逾時。

`502` 是這支獨有的。改用 `/v1/prototypes` 後實測不再出現（見下方〈Prototype 那支的實測狀況〉），但前端仍要處理，讓使用者能重按。

**三件要知道的**：

| | |
|---|---|
| **半分鐘等級** | 有獨立的 `PROTOTYPE_TIMEOUT_SECONDS`（預設 180 秒），跟第一支的 120 秒分開。實測 20～40 秒，UI 的 loading state 抓一分鐘綽綽有餘 |
| **回 200 就一定是可用網址** | 後端只在 Hermes 給出 `prototype_url` 時才回 200，否則一律 502。**不會**把錯誤訊息偽裝成網址，前端不用自己檢查字串長得像不像網址 |
| **不寫入對話記憶** | `/v1/prototypes` 只吃 `transcript`、也不回對話 ID，所以這支跟訪談那條線完全獨立 —— 下一輪追問仍接在訪談上 |

> uuid 由 Hermes server 端產生，實測 10 次全不同且都是合法 uuid4。Prototype Archive 存這個字串是安全的。

## 對話記憶

後端用 `meeting_id` 當 key，記住這場訪談問過哪些問題、以及 Hermes 的對話 ID，下一輪自動帶回去。`asked_questions` / `previous_response_id` / `response_id` 全是後端內部的事，不進出 API。

前端唯一要做的：同一場訪談固定用同一個 `meeting_id`。

實測兩輪、前端都只送 `{ text }`：第 2 輪確實會接著往下追（第 1 輪問「收入何時認列」→ 逐字稿回答後 → 第 2 輪改問「逾期未領的會計處理」）。

**但去重不保證**：實測第 2 輪出現一題跟第 1 輪語意幾乎相同（兌換流程，只多了「如何驗證票券」幾字）。提示詞規定的是「已在逐字稿中**得到明確答案**」才不再問，那輪沒人回答兌換流程，所以繼續追是合規的。UI 不能假設每輪問題互斥。

> ⚠️ 記憶存在 process 記憶體裡。**部署到 Cloud Run 必須設單一實例**，否則請求會落到沒看過前幾輪的實例上，默默退化成「第一輪」重複發問 —— 不報錯，只是變笨。

## 部署到 Cloud Run

```bash
gcloud run deploy beachcomber-be \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --min-instances=1 \
  --max-instances=1 \
  --timeout=600 \
  --set-env-vars USE_MOCK_HERMES=false
```

三個參數不能省：

| 參數 | 為什麼 |
|---|---|
| `--min-instances=1 --max-instances=1` | 對話記憶在 process 記憶體裡，多實例會讀不到、縮到零會清空。（注意：這跟 Hermes 的併發無關 —— Hermes 已放寬併發，單實例純粹是記憶體狀態的要求） |
| `--timeout=600` | 取最慢那支的最壞值。Prototype：`PROTOTYPE_ATTEMPTS=2` × `PROTOTYPE_TIMEOUT_SECONDS=180` + rate limit 等待約 30 秒 ≈ **390 秒**；Spec：`SPEC_TIMEOUT_SECONDS=300` + 等待 ≈ **325 秒**。Cloud Run 的 `--timeout` 只要低於這個數字，就會搶在後端前面砍掉請求，前端拿到的是 Cloud Run 的 504 而不是後端那個帶原因的 502 |

> ⚠️ **Cloud Run 的 timeout 是 service 層級、不能分 endpoint 設**，所以三支必須取最大的那個。上限是 3600 秒。
>
> 舊值是 `--timeout=1300`，當時被走 `/v1/responses` 的 Prototype（600 秒逾時）綁死。改走 `/v1/prototypes` 後降到 600 就夠，留著 1300 也只是多餘的 headroom，不會壞。
>
> 註：上面的算法假設 rate limit 是「立刻回 429」，所以那 6 次重試不會各自吃掉一整個 timeout。實測 429 確實是秒回。真要湊出 6 次重試各卡滿 180 秒的極端情況，數字會是 2210 秒 —— 但那代表 Hermes 本身已經掛了，拉長 Cloud Run timeout 也救不了。

## CORS

**全開，沒有任何限制，不需要設定。** 任何 origin、任何 method、任何 header 都放行，含 credentials。

```python
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",   # 不是 allow_origins=["*"]，理由見下
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

用 `allow_origin_regex=".*"` 而不是 `allow_origins=["*"]`，是因為**瀏覽器規格禁止「萬用字元 origin + 帶 credentials」** —— 填 `*` 遇到帶 cookie 的請求會被擋。regex 的做法是把對方的 Origin 原樣 echo 回去，兩種情況都能過。

實測 `http://localhost:3000`、`https://*.vercel.app`、區網 IP、以及 `null`（`file://`、sandbox iframe）都回 200 且帶正確的 `Access-Control-Allow-Origin`。

> 這是 demo 用的無認證後端，所以全開沒有實質風險（沒有 cookie 就沒有跨站盜用憑證的問題）。**要上正式環境得收回來。**

> ⚠️ 前端若是走 Next.js rewrite（`next.config.ts` 轉發 `/api/:path*`），請求是 Next 的 server 發的、**根本不會觸發 CORS**。這種設定下還看到 CORS 錯誤，代表真正的問題不是 CORS —— 通常是 rewrite 沒生效、或前端直接打了 Cloud Run 網址。

## Hermes 實測記錄

`POST https://hackathon-hermes-heh26wyhpq-de.a.run.app/v1/responses`

- **不需要 token**。agent.md 裡兩個 `Bearer ` 空著是對的，目前開放
- **endpoint 是 `/v1/responses`**，不是 `/v1/chat/completions`。body 用 `input` / `store`，不是 `messages[]`
- **併發已放寬**。原本是 `Too many concurrent runs (max 1)`，2026-09-06 實測同時發 4 個請求全部服務（1.2～2.2 秒）。撞到時仍回 HTTP `429` + `rate_limit_exceeded`，後端保留自動等 5 秒重試最多 6 次的機制，全滿才回 503
- **輸出格式不穩定**：實測有時裸 JSON、有時包在 ` ```json ` code fence 裡。兩種都要吃
- **它是 agent 不是單純的 LLM**：回應的 `output[]` 是一整串工具執行軌跡（`function_call` / `function_call_output`），最後才是 `type: "message"`。後端只撈 `content[].text`，所以只會拿到最後那則
- 追問那支約 3700 input tokens、回應 10～30 秒
- **Prototype 和 Spec 都已改走各自的專用 endpoint**（`/v1/prototypes`、`/v1/specs`），不再經過這裡。只剩第一支追問還用 `/v1/responses`

## 已知落差

`beachcomber-fe/lib/mock-data.ts` 裡的 `confidence` / `verdict` / `source` 等欄位，**Hermes 通通不會回**。api1.md 定義的輸出就只有字串陣列 `{ "questions": [...] }`。要那些欄位得改提示詞，後端才有東西可轉。詳見 contract 第五節。

`verified_count` 固定 0 —— Hermes 沒有查證機制，沒有真實來源可填。

## Prototype 那支的實測狀況

`POST /api/meetings/{meeting_id}/prototypes` → `{ "prototypes": "<GCS 網址>" }`

**這支已改走 Hermes 專用的 `/v1/prototypes`，不再自己組提示詞叫模型跑 `gcloud`。**

2026-09-06 用同一份逐字稿、兩支交錯各打 5 次的對照結果：

| | 舊 `/v1/responses` + 提示詞 | 新 `/v1/prototypes` |
|---|---|---|
| 成功率 | **0 / 5** | **5 / 5** |
| 耗時中位數 | 67.8 秒（全白花） | **33.6 秒** |
| 產出網址 | — | 5/5 HTTP 200、`<!DOCTYPE html>`、12～15 KB |

舊路徑的兩種失敗：

1. `⚠️ No reply: the model returned empty content after retries and any fallback providers.`（3/5）
2. **Hermes 說它沒有 `gcloud`**（2/5）：「我的工具集不包含執行 `gcloud` 指令的功能，因此無法完成指定的上傳步驟。」

第 2 種是致命的 —— 舊提示詞整套上傳規則建立在「Hermes 執行環境裡有 gcloud」這個前提上，而這個前提已經不成立（`/health` 回 `version: 0.21.0`，推測是平台改版收掉了，改由 `/v1/prototypes` 在 server 端負責上傳）。**重試救不回來**，所以整條路徑連同 `PROTOTYPE_PROMPT` 一起刪了。

新路徑的合約：`{"transcript": "..."}` → `{"prototype_url": "https://..."}`。

- `bucket` 欄位**傳了也沒用**，實測塞假 bucket 進去被忽略，目的地由 server 決定。`PROTOTYPE_BUCKET` 現在只剩 mock 資料在用
- `previous_responseid` / `previous_response_id` 兩種拼法傳進去都不報錯，但回應裡沒有任何 id 可以接回對話串，**當它不支援**。所以這支跟訪談那條線完全獨立
- uuid 由 server 產：實測 10 次全不同、且都是合法 uuid4。**舊的路徑碰撞問題已解決**（舊的是模型自己編，拿過 `0123456789abcdef0123456789abcdef` 這種照抄範例的佔位符，同路徑會被靜默覆蓋）

> `/v1/responses` 那條線上「`/workspace/` 跨請求共用」的問題（`write_file` 回傳夾帶過「被 sibling subagent 改過」的警告）對這支已經不適用 —— 後端不再碰 Hermes 的檔案系統。第一支追問仍走 `/v1/responses`。

## 第三隻：產 Spec

`POST /api/meetings/{meeting_id}/specs`

```jsonc
// Request — 只有 roles 必填
{ "roles": ["pm", "ui", "eng", "qa"], "transcript": "…", "prototype_url": "https://…" }
```

```jsonc
// Response — spec 是 .md 的公開網址，不是內容
{
  "response": [
    { "role": "pm", "spec": "https://storage.googleapis.com/…/specs/b7b8b118…/pm.md" }
  ]
}
```

前端只送 `{ roles }` 就能動 —— 逐字稿和 prototype 網址後端記在同一個 `meeting_id` 底下。

**這支走 Hermes 專用的 `/v1/specs`，不是對話用的 `/v1/responses`。** 所以後端不用組提示詞、不用帶對話 ID、不用自己下載 prototype HTML —— 把 `transcript` 和 `prototype_url` 丟過去，它自己產四份 Markdown 上傳 GCS 再回網址。

| | |
|---|---|
| **一次呼叫拿四份** | Hermes 一律產齊 `pm` / `ui` / `eng` / `qa`，後端依 request 的 `roles` 過濾、照 request 的順序回。只要一個角色也是同樣成本 |
| **`spec` 是網址不是內容** | 前端 `SpecViewer` 就是拿它做 `<iframe src>` 和「複製 Spec URL」，所以後端刻意不下載成 Markdown |
| **uuid 每次都不同** | 實測三次各自獨立（`3ccd7de1…` / `a403c18f…` / `b7b8b118…`），不像 prototype 那支會撞路徑 |
| **`transcript` 上限 50,000 字元** | 超過後端就擋下回 422，不浪費一次呼叫 |

實測端到端 **63～68 秒**，四個網址都可讀（7.6～10.1 KB 繁中 Markdown）。

錯誤：`422` 角色不認得／沒逐字稿可用／逐字稿超長　`502` Hermes 拒絕或沒產出（`detail` 附原因）　`503` 重試耗盡　`504` 連不上或逾時。

## 結構

```
main.py                FastAPI app、schema、三支 endpoint、對話記憶
hermes.py              追問提示詞、打 Hermes 三支 endpoint、重試、解析
test_main.py           測試（41 個，全走 mock 不出網路）
docs/api-contract.md   給前端的串接文件
```

## 還沒做

三隻都通了，prototype 的 uuid 碰撞問題也隨著改走 `/v1/prototypes` 一起解決。

剩下的：`_post_prototype()` 和 `ask_specs()` 都沒送 auth header（`_run()` 有，在 `HERMES_API_KEY` 有值時才送）。目前 Hermes 不需要 token 所以沒差，哪天要開 auth 得三支一起補。

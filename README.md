# beachcomber-be

> 這是 Beachcomber 作品的後端。作品說明、架構圖與展示連結見主 repo
> [`beachcomber-fe`](https://github.com/The-Beachcomber/beachcomber-fe)；
> AI 服務層在 [`hackathon-hermes`](https://github.com/The-Beachcomber/hackathon-hermes)。

`beachcomber-fe` 與 Hermes 之間的橋接後端。收前端的逐字稿，打 Hermes，把回來的東西轉成前端要的形狀 —— 訪談中產「接下來該追問什麼」，訪談後產「可以點的 HTML Prototype」與四份角色 Spec。

**給前端串接的人看這份**：[`docs/api-contract.md`](docs/api-contract.md)

## 跑起來

```bash
uv sync
uv run uvicorn main:app --reload --port 8000
```

- 互動式 API 文件：http://localhost:8000/docs
- 健康檢查：http://localhost:8000/health
- 測試：`uv run pytest`（41 個，全走 mock 不出網路）

`.env` 已設好可直接打真的 Hermes。改 `USE_MOCK_HERMES=true` 就回固定假資料、不出網路 —— Hermes 塞住時前端可以照常開發。

## API

三支 endpoint，都用 `meeting_id` 當同一場訪談的 key。前端唯一要做的：同一場訪談固定用同一個 `meeting_id`。

| endpoint | 收 | 回 | 耗時 |
| --- | --- | --- | --- |
| `POST /api/meetings/{id}/transcript` | `{ text }` | 追問問題清單 | 10～30 秒 |
| `POST /api/meetings/{id}/prototypes` | `{ text }` | 一個 HTML 公開網址 | 20～40 秒 |
| `POST /api/meetings/{id}/specs` | `{ roles }` | 四份 Markdown 公開網址 | 63～68 秒 |

錯誤碼三支共用同一套：`422` 參數不合格（缺欄位／角色不認得／逐字稿超過 50,000 字元）、`502` Hermes 回非 2xx 或跑完沒產出（`detail` 附原因）、`503` Hermes 忙碌重試耗盡、`504` 連不上或逾時。

### 追問問題

```jsonc
// POST /api/meetings/{meeting_id}/transcript
// Request
{ "text": "逐字稿全文" }

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

### 產 Prototype

```jsonc
// POST /api/meetings/{meeting_id}/prototypes
// Request — 跟追問那支一模一樣
{ "text": "逐字稿全文" }

// Response
{ "prototypes": "https://storage.googleapis.com/…/prototypes/f8e7d6c5…/index.html" }
```

網址可以直接塞 `<iframe>` 或開新分頁，內容是依逐字稿產的繁中單檔 HTML（CSS/JS/資料全部 inline，零外部資源）。

- **回 200 就一定是可用網址**：只在 Hermes 給出 `prototype_url` 時才回 200，否則一律 502。不會把錯誤訊息偽裝成網址，前端不用自己檢查字串長得像不像網址。
- **不寫入對話記憶**：這支跟訪談那條線完全獨立，不影響下一輪追問。
- 內容規則由 Hermes 端強制：頁面上方固定顯示「此為根據需求訪談建立的討論用 Prototype，不代表所有需求已正式簽核」、未確認需求集中在「待確認事項」區塊、示意資料標示為「原型示意資料」、所有互動只在瀏覽器本地模擬。

### 產 Spec

```jsonc
// POST /api/meetings/{meeting_id}/specs
// Request — 只有 roles 必填，逐字稿與 prototype 網址後端記在同一個 meeting_id 底下
{ "roles": ["pm", "ui", "eng", "qa"] }

// Response — spec 是 .md 的公開網址，不是內容
{
  "response": [
    { "role": "pm", "spec": "https://storage.googleapis.com/…/specs/b7b8b118…/pm.md" }
  ]
}
```

- **一次呼叫拿四份**：Hermes 一律產齊 `pm` / `ui` / `eng` / `qa`，後端依 request 的 `roles` 過濾、照 request 的順序回。只要一個角色也是同樣成本。
- **`spec` 是網址不是內容**：前端 `SpecViewer` 拿它做 `<iframe src>` 和「複製 Spec URL」，所以後端刻意不下載成 Markdown。

## 對話記憶

後端用 `meeting_id` 當 key，記住這場訪談問過哪些問題、以及 Hermes 的對話 ID，下一輪自動帶回去。`asked_questions` / `previous_response_id` / `response_id` 全是後端內部的事，不進出 API。

效果是第 2 輪會接著往下追，而不是重問（第 1 輪問「收入何時認列」→ 逐字稿回答後 → 第 2 輪改問「逾期未領的會計處理」）。

> ⚠️ 記憶存在 process 記憶體裡。**部署到 Cloud Run 必須設單一實例**，否則請求會落到沒看過前幾輪的實例上，默默退化成「第一輪」重複發問 —— 不報錯，只是變笨。

## 與 Hermes 介接

追問走 `/v1/responses`，Prototype 與 Spec 走各自的專用 endpoint（`/v1/prototypes`、`/v1/specs`）。專用 endpoint 由 Hermes server 端負責產檔與上傳 GCS，後端不組提示詞、不碰它的檔案系統。

維護時要知道的幾件事：

- **目前不需要 token**：`_run()` 在 `HERMES_API_KEY` 有值時才送 auth header。
- **`/v1/responses` 的 body 用 `input` / `store`**，不是 `messages[]`。
- **它是 agent 不是單純的 LLM**：回應的 `output[]` 是一整串工具執行軌跡（`function_call` / `function_call_output`），最後才是 `type: "message"`。後端只撈 `content[].text`。
- **輸出格式不穩定**：有時裸 JSON、有時包在 ` ```json ` code fence 裡，兩種都要吃。
- **併發撞到會回 429**（`rate_limit_exceeded`），後端自動等 5 秒重試最多 6 次，全滿才回 503。
- **產出路徑的 uuid 由 Hermes server 產**，不會碰撞，存下來當 archive key 是安全的。`bucket` 欄位傳了也沒用，目的地由 server 決定。

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
| `--min-instances=1 --max-instances=1` | 對話記憶在 process 記憶體裡，多實例會讀不到、縮到零會清空。這跟 Hermes 的併發無關，純粹是記憶體狀態的要求 |
| `--timeout=600` | 取最慢那支的最壞值：Prototype `PROTOTYPE_ATTEMPTS=2` × `PROTOTYPE_TIMEOUT_SECONDS=180` + rate limit 等待約 30 秒 ≈ 390 秒；Spec `SPEC_TIMEOUT_SECONDS=300` + 等待 ≈ 325 秒。低於這個數字，Cloud Run 會搶在後端前面砍掉請求，前端拿到的是 Cloud Run 的 504 而不是後端那個帶原因的 502 |

> ⚠️ Cloud Run 的 timeout 是 service 層級、不能分 endpoint 設，所以三支必須取最大的那個（上限 3600 秒）。

## CORS

**全開，不需要設定。** 任何 origin、method、header 都放行，含 credentials。

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

> ⚠️ 前端若走 Next.js rewrite（`next.config.ts` 轉發 `/api/:path*`），請求是 Next 的 server 發的、**根本不會觸發 CORS**。這種設定下還看到 CORS 錯誤，代表真正的問題不是 CORS —— 通常是 rewrite 沒生效、或前端直接打了 Cloud Run 網址。

## 已知限制

- **追問不保證去重**：提示詞規定的是「已在逐字稿中**得到明確答案**」才不再問，所以沒被回答到的題目會被繼續追，語意相近的問題可能跨輪重複出現。UI 不能假設每輪問題互斥。
- **`verified_count` 固定 0**：Hermes 沒有查證機制，沒有真實來源可填。
- **前端 mock 欄位無對應**：`beachcomber-fe/lib/mock-data.ts` 的 `confidence` / `verdict` / `source` Hermes 不會回，追問的輸出就只有 `{ "questions": [...] }`。要那些欄位得先改提示詞。詳見 contract 第五節。
- **CORS 全開、Hermes 免驗證**：Demo 環境刻意如此，上正式環境要收回來。
- **auth header 只有一支送**：`_post_prototype()` 和 `ask_specs()` 都沒送。目前 Hermes 不需要 token 所以沒差，哪天要開 auth 得三支一起補。

## 結構

```
main.py                FastAPI app、schema、三支 endpoint、對話記憶
hermes.py              追問提示詞、打 Hermes 三支 endpoint、重試、解析
test_main.py           測試（41 個，全走 mock 不出網路）
docs/api-contract.md   給前端的串接文件
```

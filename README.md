# Spec Agent Middleware

需求規格化 Agent 的後端中介層。

```
React 前端  ←→  本層（FastAPI / Cloud Run）  ←→  Hermes-agent (LLM)
                        ↓
                       GCS
```

契約以 [`openapi.yaml`](openapi.yaml) 為準，本專案產生的 `/openapi.json` 與其端點集合一致。

---

## 這一層存在的理由

前端只送逐字稿，**不保存也不回傳「已經問過的問題」**。但 `docs/LLM.md` 的提示詞
需要 `{{ASKED_QUESTIONS}}` 才能避免重複追問 —— 所以那份記憶必須由本層持有。

```
POST /api/meetings/{id}/transcript
  │
  ├─ 1. 逐字稿落檔                    ← 先落檔，LLM 掛掉也不會弄丟語音內容
  ├─ 2. 讀 questions/ledger.json      ← 已問問題（跨輪累積）
  ├─ 3. 呼叫 Hermes /v1/chat/completions
  │       提示詞 = docs/LLM.md 的 ``` 區塊，填入 {{TRANSCRIPT}} 與 {{ASKED_QUESTIONS}}
  ├─ 4. 正規化指紋比對，濾掉重複問題
  ├─ 5. 存活的問題寫回 ledger          ← 下一輪的過濾依據
  ├─ 6. 本輪原始產出落檔（含被丟掉的題目，供稽核）
  └─ 回傳 { "questions": [ { "question": "..." } ] }
```

### 為什麼 ledger 不能放記憶體

Cloud Run 的容器會冷啟、會擴多台、會被回收，`/tmp` 還是記憶體。一個 `dict`
在 Demo 中途就可能整包消失，或是第二台實例根本看不到第一台問過什麼。

因此 ledger 是**儲存層上的物件**，每輪 read-modify-write，並以樂觀鎖
（GCS generation precondition）處理多實例同時寫入。
`tests/test_api.py::test_ledger_survives_container_restart` 就是在斷言這件事：
換一個全新的 app 實例後，已問問題仍會被帶進下一次 LLM 呼叫。

### 去重規則

提示詞已經要求 LLM 不要重問，但那是盡力而為；中介層再擋一次：

- 比對正規化指紋（NFKC + casefold + 去除所有空白與標點），
  所以 `要保存嗎?` 與 `要保存嗎？` 視為同一題
- 同一批次內部的重複也會被丟掉
- **語意層級**的相似（換句話說問同一件事）交給 LLM 判斷，本層不做，避免誤殺

被丟掉的題目會寫進該輪落檔的 `dropped`，事後查得出為什麼少了一題。

---

## 專案結構

```
app/
  main.py              FastAPI 進入點、CORS、lifespan 預檢
  config.py            環境變數設定
  schemas.py           openapi.yaml 的 Python 投影
  deps.py              依賴注入（測試以 dependency_overrides 換掉）
  errors.py            全部收斂成 {"detail": 中文訊息}
  api/
    health.py          GET  /api/health
    meetings.py        情境 1 ＋ 輪次回讀
    transcript.py      情境 2
    artifacts.py       情境 3 / 4
  services/
    meetings.py        會議 id 與 session id 產生
    transcript.py      ★ 情境 2 的六個步驟
    questions.py       ★ 去重規則
    artifacts.py       原型頁面與角色規格文件
  llm/
    prompts.py         ★ 從 docs/LLM.md 讀提示詞（唯一真相）
    hermes.py          /v1/chat/completions client
    mock.py            不呼叫 Hermes 的假 client
  store/
    base.py            BlobStore 介面（含樂觀鎖）
    local.py           本機檔案系統（開發、測試）
    gcs.py             GCS（Cloud Run 正式環境）
    repository.py      ★ 會議 / 逐字稿 / 輪次 / ledger 存取
```

### 落檔配置

```
meetings/{meeting_id}/meeting.json
meetings/{meeting_id}/transcript.json
meetings/{meeting_id}/questions/ledger.json          ← 過濾依據
meetings/{meeting_id}/questions/round-0001.json      ← 稽核用（含 raw / dropped）
meetings/{meeting_id}/prototypes/round-0001/index.html
meetings/{meeting_id}/specs/round-0001/{role_id}.html
```

---

## 提示詞

`docs/LLM.md` 裡的 ``` 區塊是提示詞的**唯一來源**，程式啟動時解析、
只替換 `{{TRANSCRIPT}}` 與 `{{ASKED_QUESTIONS}}` 兩個佔位符。
不要在 Python 裡另抄一份 —— 抄了就會有兩份會走鐘的版本。

情境 3 / 4 的提示詞目前是 `app/llm/prompts.py` 裡的暫代版本；
正式內容確定後請比照情境 2 移進 `docs/LLM.md`。

---

## 本機開發

```bash
cp .env.example .env      # 預設 LLM_MODE=mock，不需要 Hermes 就能跑完整流程
./run.sh                  # http://localhost:8000/docs
python -m pytest -q
```

`LLM_MODE=mock` 的用途有二：前端在 LLM 還沒好之前平行開發；
Demo 當天 Hermes 掛掉時切成 mock 仍能走完流程。

### 手動驗一次情境 2

```bash
MID=$(curl -s -X POST localhost:8000/api/meetings \
  -H 'content-type: application/json' \
  -d '{"title":"黑客松主題選擇會議"}' | python -c 'import sys,json;print(json.load(sys.stdin)["meeting_id"])')

curl -s -X POST localhost:8000/api/meetings/$MID/transcript \
  -H 'content-type: application/json' -d '{"text":"我們黑客松的主題該怎麼選？"}'

curl -s -X POST localhost:8000/api/meetings/$MID/transcript \
  -H 'content-type: application/json' -d '{"text":"評審那邊有講評分標準嗎？"}'
# 第二次回傳的問題不會包含第一次已經問過的
```

---

## 部署到 Cloud Run

```bash
gcloud run deploy spec-agent-middleware \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --timeout 300 \
  --set-env-vars LLM_MODE=hermes \
  --set-env-vars HERMES_BASE_URL=https://hackathon-hermes-heh26wyhpq-de.a.run.app \
  --set-env-vars STORAGE_BACKEND=gcs \
  --set-env-vars GCS_BUCKET=<你的 bucket>
```

注意事項：

- **`--timeout 300`**：情境 3 的原型產出約 120 秒，預設 300 秒足夠；
  若之後角色數變多，情境 4 是併發呼叫，總時間不會隨角色數線性增加。
- **服務帳號需要 bucket 的 `roles/storage.objectAdmin`**。
- 產出的 HTML 要讓前端直接渲染，bucket 需開公開讀取，
  或設定 `GCS_PUBLIC_BASE_URL` 指向你的 CDN／自訂網域。
- `--max-instances` 不需要限制為 1：ledger 的樂觀鎖已處理多實例並寫。

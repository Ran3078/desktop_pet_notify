# 🐱 桌寵小提醒 Desktop Pet Notify

一隻住在 Windows 工作列上的麻糬貓。串接 Google 日曆，在活動開始前提醒你該做什麼事。

## 功能

| 類別 | 內容 |
|---|---|
| 行事曆 | 與 Google 主日曆雙向同步；Google 日曆風格的**月 / 週 / 日檢視**：日期格子、跨日色條、「+N 則」、右側當天時間軸、現在紅線 |
| 行事曆功能 | 重複活動（每天 / 每週幾 / 每月 / 每年 / 自訂間隔與結束條件，修改時可選「只有這一次 / 整個系列」）、11 種活動顏色、每個活動自訂提醒時間、台灣國定假日、農曆與節日、搜尋、雙擊或拖曳選時段快速新增、拖曳改日期 / 時間 / 長度、刪除後可復原、時間衝突提示、快捷鍵 |
| 提醒 | 預設在 10 分鐘前、1 分鐘前、開始時各提醒一次（可自訂）；泡泡上有「知道了 / 5 分鐘後再提醒 / 開啟會議」按鈕；頭上顯示倒數；系統匣同時發 Windows 通知 |
| 不打擾 | 前景是全螢幕程式時改發系統通知，離開全螢幕後補顯示泡泡；離開電腦時先保留提醒；可設定勿擾時段；電腦從睡眠喚醒後立刻同步並補發提醒 |
| 互動 | 拖到螢幕上任何位置就會停在那裡、眼睛跟著滑鼠、摸頭會開心、連點 5 下會生氣、閒置時在目前高度左右散步、伸懶腰、打哈欠 |
| 時段 | 早上打招呼、每日晨報、中午提醒吃飯、深夜睡覺 |
| 今日行程 | 可設定每天幾個固定時間（例如 09:00、13:30），桌寵會把今天所有行程列出來，並標示已結束 / 進行中；錯過的時間點 1 小時內開機仍會補發 |
| 小幫手 | 番茄鐘、喝水與伸展提醒 |
| 養成 | 好感度每 100 點升一級，升級可以解鎖配色（櫻花粉 / 薄荷 / 奶茶）與配件（蝴蝶結 / 小帽子 / 圍巾）；未解鎖的項目也會列出並標示 🔒 與所需等級 |
| 其他 | 皮膚系統（可換成自己的圖）、只允許一個實例、高 DPI 與多螢幕、閒置時降低 fps 省電、透明區域點擊穿透、開機自動啟動、可打包成 exe |

## 安裝與啟動

需求：Windows 10/11、Python 3.11 以上（開發時使用 3.13）。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

| 指令 | 說明 |
|---|---|
| `.venv\Scripts\python main.py` | 一般啟動 |
| `.venv\Scripts\python main.py --settings` | 啟動並開啟設定器 |
| `.venv\Scripts\python main.py --debug` | 輸出 DEBUG 等級 log |
| `.venv\Scripts\pythonw main.py` | 不開主控台視窗啟動 |

本程式不使用網路 port，也不需要環境變數。Google 授權時會在 localhost 開一個隨機 port 接收回傳結果，授權完成後就會關閉。

### 操作方式
- **左鍵拖曳**：把桌寵移到任何位置，放開後就停在那裡（不會超出螢幕，下次啟動也會記得位置）
- **左鍵點一下**：摸摸頭（每分鐘最多加 1 點好感度）
- **雙擊**：看接下來的 3 個行程
- **右鍵**：選單，包括設定器、同步、番茄鐘、隱藏、結束
- **系統匣圖示**：點一下開啟設定器；右鍵可以顯示或隱藏桌寵

## 設定 Google 日曆（OAuth）

第一次使用需要建立自己的 OAuth 憑證，只需設定一次：

1. 打開 [Google Cloud Console](https://console.cloud.google.com/)，在左上角專案選單選「新增專案」，名稱隨意（例如 `desktop-pet`）。
2. 到 **API 和服務 → 程式庫**，搜尋 **Google Calendar API**，按「啟用」。
3. 到 **API 和服務 → OAuth 同意畫面**（新版介面叫 **Google Auth Platform**）：
   - 使用者類型選 **外部（External）**
   - 填入應用程式名稱與你的 Email
   - 在 **目標對象 / 測試使用者** 加入你自己的 Google 帳號
4. 到 **API 和服務 → 憑證 → 建立憑證 → OAuth 用戶端 ID**：
   - 應用程式類型選 **電腦版應用程式（Desktop app）**
   - 建立後按「下載 JSON」
5. 把下載的檔案改名為 `credentials.json`，放到專案根目錄（打包版則放在 `DesktopPet.exe` 旁邊）。
6. 啟動桌寵 → 開啟設定器 →「行事曆」分頁 → **登入 Google**。瀏覽器會開啟授權頁面：
   - 如果看到「Google 尚未驗證這個應用程式」，按「繼續」即可（這是你自己建立的應用程式）
   - 授權完成後會產生 `token.json`，之後會自動更新，不需要重新登入

> 使用的權限範圍是 `calendar.events`，只能讀寫活動，無法修改日曆本身的設定。
> `credentials.json` 和 `token.json` 都已列入 `.gitignore`，請不要上傳或分享給別人。

**常見問題**
- 不小心關掉授權分頁：設定器的按鈕會顯示「取消登入」，按下後再重新登入即可。等超過 3 分鐘也會自動取消。
- 授權失敗並出現 `access_denied`：確認第 3 步已把自己加入測試使用者。
- 每 7 天要重新登入一次：OAuth 同意畫面還在「測試中」時，Google 的 refresh token 只有 7 天效期。要長期使用，可以在同意畫面按「發布應用程式」（自用不需要送審）。

## 行事曆操作

| 操作 | 方式 |
|---|---|
| 切換月份 / 週 / 天 | 工具列「‹ ›」、滑鼠滾輪（月檢視）、鍵盤 ← → |
| 看某天的行程 | 月檢視點日期格子，右側面板顯示當天時間軸 |
| 快速新增 | 月檢視雙擊日期格子（全天活動）；時間軸上拖曳空白處選時段，或雙擊空白處 |
| 改日期 / 時間 | 月檢視拖曳活動到別天；時間軸拖曳活動改時間，拖曳下緣改長度 |
| 編輯 / 刪除 | 點活動打開卡片 →「編輯」或「刪除」；刪除後底部提示列 6 秒內可按「復原」 |
| 搜尋 | 工具列搜尋框輸入後按 Enter（範圍：前後各一年） |
| 顯示設定 | 工具列 ⚙：一週的第一天、顯示農曆、顯示國定假日 |

快捷鍵：`T` 今天、`←` `→` 上下一段、`M` `W` `D` 月 / 週 / 日、`N` 新增、`/` 搜尋、`Delete` 刪除選取的活動。

- 重複活動的「只有這一次 / 整個系列」：改整個系列的時間時，會把這一次的位移套用到整個系列。
- 個別提醒：活動設定自訂提醒時，桌寵就照該活動的時間提醒；選「使用預設」則用通知分頁的全域設定。
- 國定假日來自 Google 公開的「台灣節日」日曆；若帳號權限讀不到，就只是不顯示假日（log 會記 WARNING）。
- 農曆使用 Windows 內建的 ICU，不需安裝額外套件。

## 自訂皮膚

把資料夾放到 `data/skins/<名稱>/`，裡面要有 `skin.json` 和 sprite sheet，然後在設定器的「桌寵」分頁選擇。格式請參考 `assets/skins/sample/`，可以用 `tools/make_sample_skin.py` 重新產生：

```json
{
  "name": "我的桌寵",
  "frame_size": [140, 120],
  "sheet": "sheet.png",
  "flip_when_left": true,
  "states": {
    "idle":  {"row": 0, "frames": 4, "fps": 4},
    "walk":  {"row": 1, "frames": 4, "fps": 8}
  }
}
```

- 每個狀態佔一列，從左到右依序是各影格。只有 `idle` 是必要的，沒定義的狀態會自動退回相近的狀態。
- 可用狀態：`idle walk sit stretch yawn drag happy angry alert sleep pomodoro celebrate greet`
- 倒數小牌、愛心、驚嘆號、zzz 這些特效由程式疊加，不用畫進圖片裡。
- 點擊判定依照圖片的透明度，透明的地方點下去會穿透到下面的視窗。

## 打包成 exe

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python tools\make_icon.py          # 產生 assets\icon.ico（已附上，改圖示時才需要）
.venv\Scripts\pyinstaller build.spec --noconfirm
```

輸出為 `dist\DesktopPet\DesktopPet.exe`，整個資料夾約 250 MB，大部分是 Qt 與音效用的 FFmpeg。設定、log 和 Google 憑證都存在 exe 旁邊。

## 檔案位置

| 路徑 | 內容 |
|---|---|
| `logs/app.log` | 執行記錄，每個檔案 1 MB、保留 5 份輪替；含時間戳、層級與錯誤 traceback |
| `data/settings.json` | 設定 |
| `data/pet_state.json` | 好感度、已提醒紀錄 |
| `data/events_cache.json` | 活動離線快取 |
| `data/sounds/` | 內建音效（第一次啟動時產生） |

## 開發

```powershell
.venv\Scripts\python -m unittest discover -s tests -t .
```

```
pet_notify/
├─ app.py              主控：串接所有元件
├─ cal/                Google 日曆（OAuth、API、背景同步、快取）
├─ reminders/          提醒排程、不打擾、通知中心、晨報、番茄鐘、健康提醒
├─ pet/                桌寵視窗、行為狀態機、物理、泡泡、皮膚
├─ ui/                 設定器、活動對話框
├─ tray.py             系統匣
├─ sound.py            音效
├─ win_sys.py          全螢幕 / 閒置偵測、開機自動啟動（ctypes / winreg）
└─ single_instance.py  只允許一個實例
```

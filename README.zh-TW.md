# doggybag 🥡

[English](README.md) · 繁體中文

Claude 訂閱額度快過期還有剩，就跑你自己的 script。吃不完的，打包帶走。

doggybag 只負責「什麼時候跑」。要跑什麼由你決定：一段 prompt、一個 skill，或你自己的程式都可以。

## 需求

- macOS（自動排程目前只支援 macOS；Linux 可以用 cron 呼叫 `doggybag run`）
- Python 3.11 以上
- 已登入的 [Claude Code](https://claude.com/claude-code)

## 安裝

```bash
uv tool install .        # 或 pipx install .
doggybag setup
```

`setup` 會檢查 Claude Code、建立 `~/.doggybag/`、放入範例，並安裝每 10 分鐘檢查一次的排程。

## 三個指令

| 指令 | 做什麼 |
|---|---|
| `doggybag setup` | 檢查環境、安裝排程。`--no-schedule` 不裝排程，`--uninstall` 移除排程 |
| `doggybag status` | 顯示目前額度，以及每個 task 現在會不會跑、為什麼 |
| `doggybag run` | 檢查一次，跑條件成立的 task。`doggybag run <task>` 立刻跑指定的 task，不看條件 |

## 寫一個 task

一個檔案就是一個 task。把可執行檔放進 `~/.doggybag/tasks/`，條件寫在檔案開頭的註解裡：

```bash
#!/bin/bash
# doggybag:
#   when: 5h.resets_in <= 60m and 5h.remaining >= 30
#   when: idle >= 60m and week.behind >= 20
#   cooldown: 6h
#   timeout: 30m

cd ~/work/myrepo
claude -p "Review the three most recent commits." --allowedTools "Read" "Grep" "Glob"
```

- 同一行用 `and` 連接，全部成立才算。
- 有多行 `when:` 時，任一行成立就觸發。
- task 依檔名順序檢查，一次只跑一個。
- 沒有 `when:` 的 task 不會自動跑，只能用 `doggybag run <task>` 手動跑。
- 要停用一個 task，拿掉執行權限（`chmod -x`）或把它移出資料夾。
- 註解符號可以是 `#`、`//`、`--` 或 `;`，所以 task 不限語言。

### 可用的訊號

`5h` 是 5 小時窗口，`week` 是週額度。

| 訊號 | 意思 | 例子 |
|---|---|---|
| `5h.remaining`、`week.remaining` | 還剩多少 % | `week.remaining >= 40` |
| `5h.used`、`week.used` | 已用多少 % | `5h.used <= 20` |
| `5h.resets_in`、`week.resets_in` | 離 reset 多久 | `5h.resets_in <= 60m` |
| `5h.behind`、`week.behind` | 用量落後時間進度幾個百分點 | `week.behind >= 20` |
| `idle` | 多久沒有人消耗額度 | `idle >= 60m` |

`behind` 的算法：窗口的時間過了 40%，額度只用了 10%，就是落後 30。
時間的單位是 `m`、`h`、`d`。

### 其他設定

| 設定 | 預設 | 意思 |
|---|---|---|
| `cooldown` | `5h` | 跑完後多久內不再觸發 |
| `timeout` | `1h` | 跑超過這個時間就中止 |

### doggybag 和 task 之間的約定

doggybag 會傳入這些環境變數：

| 變數 | 內容 |
|---|---|
| `DOGGYBAG_TASK` | task 的檔名 |
| `DOGGYBAG_REASON` | 觸發的原因 |
| `DOGGYBAG_5H_REMAINING`、`DOGGYBAG_WEEK_REMAINING` | 剩餘 % |
| `DOGGYBAG_5H_RESETS_AT`、`DOGGYBAG_WEEK_RESETS_AT` | reset 時間（epoch 秒） |
| `DOGGYBAG_LOG` | 這次執行的 log 檔路徑 |

task 用 exit code 回報結果：`0` 是完成，`75` 是「現在沒事可做」（不算失敗，也不進 cooldown），其他是失敗。

task 的輸出會寫到 `~/.doggybag/logs/`。

## 煞車

doggybag 不知道 task 會花多少額度，所以它在 task 執行期間每 5 分鐘重讀一次額度。
剩餘額度低於保留線時，它會送 SIGTERM 給 task（30 秒後還沒結束就強制停止），也不再開下一個。

保留線寫在 `~/.doggybag/config.toml`：

```toml
reserve_5h = 10      # 5 小時窗口至少留 10%
reserve_week = 5     # 週額度至少留 5%
notify = true        # task 開始和結束時發桌面通知
interval_minutes = 10
```

## 讓 Claude 在沒人的時候做事

doggybag 觸發 task 時你通常不在電腦前，Claude 沒辦法問你「可以嗎」，沒被允許的動作會直接被擋下。
所以 task 要用 `--allowedTools` 事先列出可以用的工具。範例只開放讀檔和搜尋，需要改檔案時再自己加。

只有透過已登入的 `claude` 指令跑的東西才會用到訂閱額度。用 API key 的程式是另外計費的。

## 已知限制

- **電腦要醒著。** 排程在 Mac 睡眠時不會執行。
- **額度來自 `claude -p "/usage"` 的文字輸出。** 這個呼叫不花額度，doggybag 也不碰你的登入憑證，但輸出格式改版時解析會壞（最後驗證：Claude Code 2.1.330）。
- **用量的解析度是 1%。** 很小的消耗 `idle` 看不出來。
- **`idle` 只在 doggybag 檢查時更新。** 它是從「上一次看到用量增加」算起。
- **沒有進行中的 5 小時窗口時**，`5h.resets_in` 和 `5h.behind` 的條件一律不成立。這個狀況下 `/usage` 的實際輸出還沒驗證過。

## 開發

```bash
python3 -m unittest discover -s tests
```

用 `DOGGYBAG_HOME` 可以把 `~/.doggybag` 換到別的位置，方便測試。

## 授權

[MIT](LICENSE)

# doggybag 🥡

[English](README.md) · 繁體中文

**Claude 訂閱額度不管有沒有用完，時間到就會重置。doggybag 在額度過期前，用剩下的部分跑你自己的 script。**

1. 你把 script 放進一個資料夾。
2. 每個 script 在開頭的註解裡寫明什麼時候該跑。
3. doggybag 每 10 分鐘檢查一次額度，條件成立的就跑。

doggybag 只決定「什麼時候」。要跑什麼由你決定：一段 prompt、一個 skill，或你自己的程式。

## 快速開始

需要 macOS、Python 3.11 以上，以及已登入的 [Claude Code](https://claude.com/claude-code)。

```bash
# 1. 安裝並設定（會建立 ~/.doggybag，並安裝每 10 分鐘檢查一次的排程）
uv tool install git+https://github.com/toeric/doggybag    # 或 pipx install git+https://github.com/toeric/doggybag
doggybag setup

# 2. 加入一個 task：把範例複製到 tasks 資料夾
cp ~/.doggybag/tasks/examples/a-prompt.sh ~/.doggybag/tasks/10-review.sh

# 3. 編輯它（什麼時候跑、跑什麼），然後啟用
open -e ~/.doggybag/tasks/10-review.sh
chmod +x ~/.doggybag/tasks/10-review.sh

# 4. 看 doggybag 怎麼判斷
doggybag status
```

`status` 會告訴你每個 task 現在會不會跑，以及原因：

```text
5h     60% left · resets in 2h55m (Sun 17:59) · +2 behind pace
week   95% left · resets in 6d5h (Sat 20:59) · +6 behind pace

· 10-review.sh
    waiting: 5h.resets_in <= 1h (no, now 2h55m) and 5h.remaining >= 30% (yes, now 60%)
```

這樣就完成了。不需要註冊任何東西：**task 就是 `~/.doggybag/tasks/` 裡的一個檔案。**

## task 長什麼樣子

開頭寫什麼時候跑，其餘是你要做的事。

```bash
#!/bin/bash
# doggybag:
#   when: 5h.resets_in <= 60m and 5h.remaining >= 30
#   cooldown: 6h

cd ~/work/myrepo
claude -p "Review the three most recent commits." --allowedTools "Read" "Grep" "Glob"
```

### 「when」的常用寫法

| 我想在這個時候跑 | 寫法 |
|---|---|
| 5 小時窗口快重置，而且還剩很多 | `when: 5h.resets_in <= 60m and 5h.remaining >= 30` |
| 一小時沒有人用 Claude | `when: idle >= 60m` |
| 週額度用得比時間過得慢 | `when: week.behind >= 20` |
| 一週的最後一天，而且還剩很多 | `when: week.resets_in <= 1d and week.remaining >= 40` |
| 兩種情況任一發生 | 寫兩行 `when:`，一行一種情況 |

### 管理 task

| 想做的事 | 做法 |
|---|---|
| 加入 task | 把可執行檔放進 `~/.doggybag/tasks/` |
| 移除 task | 刪掉檔案 |
| 暫時停用 | 對檔案下 `chmod -x` |
| 調整順序 | 改檔名，doggybag 依檔名順序檢查 |
| 立刻試跑 | `doggybag run 10-review`（不看條件） |

### 三種 task

`doggybag setup` 會在 `~/.doggybag/tasks/examples/` 各放一個範例。

| 範例 | 跑什麼 |
|---|---|
| `a-prompt.sh` | 一段 prompt，用 `claude -p "..."` |
| `b-skill.sh` | 你自己的 Claude Code skill，用 `claude -p "/my-skill"` |
| `c-own-program.py` | 你自己的任何程式 |

有兩件事要知道：

- **沒有人可以按「允許」。** doggybag 觸發 task 時你通常不在電腦前，沒有事先允許的動作會被擋下。用 `--allowedTools` 列出 task 可以用的工具。範例只開放讀檔和搜尋。
- **只有已登入的 `claude` 指令會用到訂閱額度。** 用 API key 呼叫 API 的程式是另外計費的。

## 三個指令

| 指令 | 做什麼 |
|---|---|
| `doggybag setup` | 檢查環境、安裝排程。`--no-schedule` 不裝排程，`--uninstall` 移除排程 |
| `doggybag status` | 顯示額度，以及每個 task 現在會不會跑、為什麼 |
| `doggybag run` | 檢查一次，跑條件成立的 task。`doggybag run <task>` 立刻跑指定的 task |

## 參考

### 條件

- 同一行用 `and` 連接的條件要全部成立。
- 有多行 `when:` 時，任一行成立就觸發。
- 沒有 `when:` 的 task 不會自動跑，只能用 `doggybag run <task>` 手動跑。
- task 依檔名順序檢查，一次只跑一個。
- 註解符號可以是 `#`、`//`、`--` 或 `;`，所以 task 不限語言。

`5h` 是 5 小時窗口，`week` 是週額度。

| 訊號 | 意思 | 例子 |
|---|---|---|
| `5h.remaining`、`week.remaining` | 還剩多少 % | `week.remaining >= 40` |
| `5h.used`、`week.used` | 已用多少 % | `5h.used <= 20` |
| `5h.resets_in`、`week.resets_in` | 離重置多久 | `5h.resets_in <= 60m` |
| `5h.behind`、`week.behind` | 用量落後時間進度幾個百分點 | `week.behind >= 20` |
| `idle` | 多久沒有人消耗額度 | `idle >= 60m` |

`behind` 的算法：窗口的時間過了 40%，額度只用了 10%，就是落後 30。
時間的單位是 `m`、`h`、`d`。

| 設定 | 預設 | 意思 |
|---|---|---|
| `cooldown` | `5h` | 跑完後多久內不再觸發 |
| `timeout` | `1h` | 跑超過這個時間就中止 |

### doggybag 傳給 task 的資訊

| 變數 | 內容 |
|---|---|
| `DOGGYBAG_TASK` | task 的檔名 |
| `DOGGYBAG_REASON` | 觸發的原因 |
| `DOGGYBAG_5H_REMAINING`、`DOGGYBAG_WEEK_REMAINING` | 剩餘 % |
| `DOGGYBAG_5H_RESETS_AT`、`DOGGYBAG_WEEK_RESETS_AT` | 重置時間（epoch 秒） |
| `DOGGYBAG_LOG` | 這次執行的 log 檔路徑 |

task 用 exit code 回報結果：`0` 是完成，`75` 是「現在沒事可做」（不算失敗，也不進 cooldown），其他是失敗。

task 的輸出會寫到 `~/.doggybag/logs/`。

### 煞車

doggybag 不知道 task 會花多少額度，所以它在 task 執行期間每 5 分鐘重讀一次額度。
剩餘額度低於保留線時，它會送 SIGTERM 給 task（30 秒後還沒結束就強制停止），也不再開下一個。

保留線寫在 `~/.doggybag/config.toml`：

```toml
reserve_5h = 10      # 5 小時窗口至少留 10%
reserve_week = 5     # 週額度至少留 5%
notify = true        # task 開始和結束時發桌面通知
interval_minutes = 10
```

### 已知限制

- **電腦要醒著。** 排程在 Mac 睡眠時不會執行。
- **自動排程目前只支援 macOS。** Linux 可以用 cron 呼叫 `doggybag run`。
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

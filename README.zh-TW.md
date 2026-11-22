# doggybag 🥡

[English](README.md) · 繁體中文

**Claude 訂閱額度不管有沒有用完，時間到就會重置。doggybag 在額度過期前，用剩下的部分跑你自己的 script。**

1. 你把 task 放進一個資料夾。task 可以是一個寫著 prompt 的文字檔，或任何 script。
2. 每個 task 在開頭寫明什麼時候該跑。
3. doggybag 每 10 分鐘檢查一次額度，條件成立的就跑。

doggybag 只決定「什麼時候」。要跑什麼由你決定：一段 prompt、一個 skill，或你自己的程式。

## 快速開始

需要 macOS、Python 3.11 以上，以及已登入的 [Claude Code](https://claude.com/claude-code)。

```bash
# 1. 安裝並設定
uv tool install git+https://github.com/toeric/doggybag    # 或 pipx install git+https://github.com/toeric/doggybag
doggybag setup

# 2. 打開 setup 幫你建好的第一個 task
open -e ~/.doggybag/tasks/10-review.md

# 3. 看 doggybag 怎麼判斷
doggybag status
```

`setup` 會建立 `~/.doggybag`、安裝每 10 分鐘檢查一次的排程，並幫你寫好第一個 task。這個 task 在你編輯之前是關閉的：

```markdown
---
when: leftover
in: ~/path/to/your/repo
enabled: false
---
Review the three most recent commits in this repository.
List anything that looks risky, and say which file and line it is in.
```

改三個地方：`in:` 後面的資料夾、prompt 的內容，以及把 `enabled: false` 改成 `true`。不需要註冊任何東西：**task 就是 `~/.doggybag/tasks/` 裡的一個檔案。**

`status` 會告訴你每個 task 現在會不會跑，以及原因：

```text
5h     60% left · resets in 2h55m (Sun 17:59) · +2 behind pace
week   95% left · resets in 6d5h (Sat 20:59) · +6 behind pace

· 10-review.md
    waiting: 5h.resets_in <= 1h (no, now 2h55m) and 5h.remaining >= 30% (yes, now 60%)
```

## 什麼時候跑

大部分情況寫一個詞就夠了：

| 寫法 | 什麼時候跑 |
|---|---|
| `when: leftover` | 5 小時窗口在一小時內重置，而且至少還剩 30% |
| `when: idle` | 一小時沒有人用 Claude |
| `when: behind` | 週額度用得比時間過得慢 |

可以用 `and` 組合，也可以寫多行 `when:`。任一行成立就會觸發。

```yaml
when: idle and behind
when: leftover
```

這三個詞不合用時，可以自己寫數字：

| 我想在這個時候跑 | 寫法 |
|---|---|
| 窗口最後 30 分鐘，而且還剩一半 | `when: 5h.resets_in <= 30m and 5h.remaining >= 50` |
| 閒置三小時之後 | `when: idle >= 3h` |
| 一週的最後一天，而且還剩很多 | `when: week.resets_in <= 1d and week.remaining >= 40` |

完整的訊號列表在[參考](#參考)。

## task 的兩種寫法

### prompt 檔

最簡單的 task 是一個 `.md` 檔。設定寫在兩行 `---` 之間，下面全部是 prompt。

```markdown
---
when: leftover
in: ~/work/myrepo
tools: Read, Grep, Glob
---
Review the three most recent commits and list anything risky.
```

| 設定 | 意思 | 沒寫的話 |
|---|---|---|
| `when` | 什麼時候跑 | 只能手動跑 |
| `in` | Claude 工作的資料夾 | tasks 資料夾 |
| `tools` | Claude 不用問就能做的事。`none` 表示都不允許 | `Read, Grep, Glob`（只能讀檔和搜尋） |
| `model` | 用哪個模型 | 你的 Claude Code 預設值 |

要跑你自己的 Claude Code skill，把 prompt 寫成 `/my-skill` 就可以。

doggybag 跑 task 時沒有人可以按「允許」，所以 Claude 只能用 `tools` 列出的工具。task 需要改檔案時，自己加上 `Edit` 和 `Write`。

### script

需要的不只是一段 prompt 時，用任何語言寫一個 script。設定寫在開頭的註解裡，檔案要有執行權限（`chmod +x`）。

```bash
#!/bin/bash
# doggybag:
#   when: leftover
#   cooldown: 6h

cd ~/work/myrepo
git pull
claude -p "Review the three most recent commits." --allowedTools "Read" "Grep" "Glob"
```

只有已登入的 `claude` 指令會用到訂閱額度。用 API key 呼叫 API 的程式是另外計費的。

`~/.doggybag/tasks/examples/` 裡各有一個範例：prompt 檔、跑 prompt 的 script、跑 skill 的 script，以及呼叫你自己程式的 script。

## 管理 task

| 想做的事 | 做法 |
|---|---|
| 加入 task | 把檔案放進 `~/.doggybag/tasks/` |
| 移除 task | 刪掉檔案 |
| 暫時停用 | 設定 `enabled: false` |
| 調整順序 | 改檔名，doggybag 依檔名順序檢查 |
| 立刻試跑 | `doggybag run 10-review`（不看 `when` 和 `enabled`） |

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
- script 的註解符號可以是 `#`、`//`、`--` 或 `;`。

三個詞分別等於：

| 詞 | 等於 |
|---|---|
| `leftover` | `5h.resets_in <= 60m and 5h.remaining >= 30` |
| `idle` | `idle >= 60m` |
| `behind` | `week.behind >= 20` |

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

### 每個 task 都能用的設定

| 設定 | 預設 | 意思 |
|---|---|---|
| `when` | 無 | 什麼時候跑，可以寫多行 |
| `cooldown` | `5h` | 跑完後多久內不再觸發 |
| `timeout` | `1h` | 跑超過這個時間就中止 |
| `enabled` | `true` | 設成 `false` 就停用這個 task |

prompt 檔另外可以用 `in`、`tools`、`model`，說明在上面。

### doggybag 傳給 task 的資訊

| 變數 | 內容 |
|---|---|
| `DOGGYBAG_TASK` | task 的檔名 |
| `DOGGYBAG_REASON` | 觸發的原因 |
| `DOGGYBAG_5H_REMAINING`、`DOGGYBAG_WEEK_REMAINING` | 剩餘 % |
| `DOGGYBAG_5H_RESETS_AT`、`DOGGYBAG_WEEK_RESETS_AT` | 重置時間（epoch 秒） |
| `DOGGYBAG_LOG` | 這次執行的 log 檔路徑 |

script 用 exit code 回報結果：`0` 是完成，`75` 是「現在沒事可做」（不算失敗，也不進 cooldown），其他是失敗。

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

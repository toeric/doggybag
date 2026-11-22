# doggybag 🥡

[English](README.md) · 繁體中文

**Claude 訂閱額度不管有沒有用完，時間到就會重置。doggybag 在額度過期前，把剩下的部分用在你指定的工作上。**

## 它長什麼樣子

一件工作就是一個文字檔。下面是一個完整的例子：

```markdown
---
when: leftover
in: ~/work/myrepo
---
Find the TODO and FIXME comments in this repository.
Pick the five that are most worth fixing.
```

它的意思是：**額度快重置而且還有剩的時候，到這個資料夾做這件事。**

每件工作都是同樣的三個部分：

| 部分 | 回答什麼 | 在這個例子裡 |
|---|---|---|
| `when:` | 什麼時候跑 | 額度快重置而且還有剩 |
| `in:` | 在哪裡跑 | `~/work/myrepo` |
| 下面的文字 | 做什麼 | 找出 TODO 註解 |

doggybag 每 10 分鐘檢查一次額度。時機到了，它把這段文字交給 Claude Code，再把回答存成檔案。你不需要在電腦前。

想讓 Claude Code 以外的東西來做？加一行 `run:`，文字就會改交給那個指令。[後面有說明。](#把工作交給別的東西)

## 開始使用

需要 macOS、Python 3.11 以上，以及已登入的 [Claude Code](https://claude.com/claude-code)。

**1. 安裝**

```bash
uv tool install git+https://github.com/toeric/doggybag    # 或 pipx install git+https://github.com/toeric/doggybag
doggybag setup
```

`setup` 會建立 `~/.doggybag/tasks/` 資料夾，並放進第一件工作，就是上面那個例子。在你編輯之前它是關閉的。

**2. 編輯第一件工作**

```bash
open -e ~/.doggybag/tasks/10-todo-triage.md
```

把 `in:` 後面的資料夾改成你自己的專案，再把 `enabled: false` 改成 `true`。

**3. 確認**

```bash
doggybag status
```

```text
5h     60% left · resets in 2h55m (Sun 17:59) · +2 behind pace
week   95% left · resets in 6d5h (Sat 20:59) · +6 behind pace

· 10-todo-triage.md
    waiting: 5h.resets_in <= 1h (no, now 2h55m) and 5h.remaining >= 30% (yes, now 60%)
```

這樣就完成了，條件成立時它會自己跑。想馬上看到結果，執行 `doggybag run 10-todo-triage`。

## 範例

六件現成的工作。`setup` 會把它們複製到 `~/.doggybag/tasks/examples/`。

**使用方式：**把檔案複製到 `~/.doggybag/tasks/`，改 `in:` 後面的資料夾，再把 `enabled: false` 改成 `true`。

每個範例的排列方式都一樣：第一行說明它做什麼，接著是設定，最後是工作的文字。

| 範例 | 做什麼 | 什麼時候跑 | 會改你的檔案嗎 |
|---|---|---|---|
| [todo-triage.md](src/doggybag/examples/todo-triage.md?plain=1) | 列出最值得修的五個 TODO 註解 | 額度快重置而且還有剩 | 不會 |
| [docs-check.md](src/doggybag/examples/docs-check.md?plain=1) | 找出 README 和程式碼不一致的地方 | 這週的額度用得比較慢 | 不會 |
| [write-tests.md](src/doggybag/examples/write-tests.md?plain=1) | 幫測試最少的檔案寫測試。這件工作可以改檔案 | 一小時沒人用 Claude，而且這週用得比較慢 | 會，只改 tests 資料夾 |
| [run-skill.md](src/doggybag/examples/run-skill.md?plain=1) | 跑你自己的 Claude Code skill。把 /my-skill 換成它的名稱 | 一小時沒人用 Claude | 看 skill 的內容 |
| [review-commits.md](src/doggybag/examples/review-commits.md?plain=1) | 用 run: 整理最近的 commit，交給 Claude 檢查 | 額度快重置而且還有剩 | 不會 |
| [own-agent.md](src/doggybag/examples/own-agent.md?plain=1) | 用 run: 把下面的文字交給你自己的程式 | 一週的最後一天，而且還剩很多 | 看你的程式 |

每個範例的完整內容：

<details>
<summary><code>todo-triage.md</code></summary>

```markdown
---
# Lists the five TODO comments most worth fixing.
when: leftover
in: ~/path/to/your/repo
cooldown: 6h
enabled: false
---
Find the TODO and FIXME comments in this repository.

Pick the five that are most worth fixing. For each one, give the file and line,
say in one sentence what is wrong, and say how much work a fix would be.
```

</details>

<details>
<summary><code>docs-check.md</code></summary>

```markdown
---
# Finds places where the README no longer matches the code.
when: behind
in: ~/path/to/your/repo
cooldown: 1d
enabled: false
---
Compare README.md with the code in this repository.

List every place where the README describes something the code no longer does:
commands, options, file paths, or behaviour. Quote the README line and say what
the code does instead. If everything matches, say so in one line.
```

</details>

<details>
<summary><code>write-tests.md</code></summary>

```markdown
---
# Writes tests for the least-tested file. Allowed to change files.
when: idle and behind
in: ~/path/to/your/repo
tools: Read, Grep, Glob, Edit, Write
cooldown: 1d
timeout: 45m
enabled: false
---
Find the source file in this repository that has the least test coverage.

Write tests for it in the existing tests folder, following the style of the
tests that are already there. Only add or change files inside the tests folder.
End with a list of the files you touched.
```

</details>

<details>
<summary><code>run-skill.md</code></summary>

```markdown
---
# Runs one of your own Claude Code skills. Replace /my-skill with its name.
when: idle
in: ~/path/to/your/repo
cooldown: 12h
enabled: false
---
/my-skill
```

</details>

<details>
<summary><code>review-commits.md</code></summary>

```markdown
---
# Uses run: to collect the latest commits and pipe them to Claude for review.
when: leftover
in: ~/path/to/your/repo
run: git log -3 --patch | claude -p "Review these commits. List anything that looks risky."
cooldown: 6h
enabled: false
---
```

</details>

<details>
<summary><code>own-agent.md</code></summary>

```markdown
---
# Uses run: to hand the text below to a program of your own.
when: week.resets_in <= 1d and week.remaining >= 40
in: ~/path/to/your/repo
run: python3 ~/agents/my_agent.py
cooldown: 1d
enabled: false
---
Find the TODO comments in this repository and pick the five most worth fixing.
```

</details>

## 結果在哪裡

工作印出的所有內容都存在 `~/.doggybag/logs/`。`doggybag status` 會列出每件工作上次執行的檔案：

```text
· 10-todo-triage.md
    last run Nov 22 18:50 (exit 0) · output: ~/.doggybag/logs/10-todo-triage-20261122-185043.log
```

工作開始和結束時，你也會收到桌面通知。

## 什麼時候跑

通常寫一個詞就夠了：

| 寫法 | 什麼時候跑 |
|---|---|
| `when: leftover` | 5 小時窗口在一小時內重置，而且至少還剩 30% |
| `when: idle` | 一小時沒有人用 Claude |
| `when: behind` | 週額度用得比時間過得慢 |

可以用 `and` 組合。有多行 `when:` 時，任一行成立就會跑。

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

## Claude 可以做什麼

工作執行時沒有人可以按「允許」，所以 Claude 只能用這件工作列出的工具。

```yaml
tools: Read, Grep, Glob                 # 預設：只能讀檔和搜尋
tools: Read, Grep, Glob, Edit, Write    # 也可以改檔案
```

沒寫 `tools:` 的工作只能讀。

## 把工作交給別的東西

工作的文字預設交給 Claude Code。加上 `run:`，就改交給那個指令。其他部分完全不變。

**你自己的 agent。** 設定下面的文字就是你的程式收到的輸入：

```markdown
---
when: idle
in: ~/work/myrepo
run: python3 ~/agents/my_agent.py
---
Find the TODO comments and pick the five most worth fixing.
```

**不需要指示的 script。** 文字留空就好：

```markdown
---
when: leftover
in: ~/work/myrepo
run: ./scripts/nightly-review.sh
---
```

**一行的管線。** `run:` 是 shell 指令，所以也可以這樣寫：

```markdown
---
when: leftover
in: ~/work/myrepo
run: git log -3 --patch | claude -p "Review these commits. List anything risky."
---
```

有兩件事要知道：

- `tools:` 和 `model:` 是給 Claude Code 的設定，不能和 `run:` 一起用。
- 只有已登入的 `claude` 指令會用到訂閱額度。用 API key 呼叫 API 的程式是另外計費的。

## 管理工作

| 想做的事 | 做法 |
|---|---|
| 加入工作 | 把檔案放進 `~/.doggybag/tasks/` |
| 移除工作 | 刪掉檔案 |
| 暫時停用 | 設定 `enabled: false` |
| 調整順序 | 改檔名，doggybag 依檔名順序檢查 |
| 立刻試跑 | `doggybag run 10-todo-triage`（不看 `when` 和 `enabled`） |

## 三個指令

| 指令 | 做什麼 |
|---|---|
| `doggybag setup` | 檢查環境、安裝排程。`--no-schedule` 不裝排程，`--uninstall` 移除排程 |
| `doggybag status` | 顯示額度，以及每個 task 現在會不會跑、為什麼 |
| `doggybag run` | 檢查一次，跑條件成立的 task。`doggybag run <task>` 立刻跑指定的 task |

## 參考

需要時再查的細節。程式和指令裡把一件工作稱為 task。

### 條件

- 同一行用 `and` 連接的條件要全部成立。
- 有多行 `when:` 時，任一行成立就觸發。
- 沒有 `when:` 的 task 不會自動跑，只能用 `doggybag run <task>` 手動跑。
- task 依檔名順序檢查，一次只跑一個。
- 只有直接放在 `~/.doggybag/tasks/` 裡的 `.md` 檔是 task。其他檔案和子資料夾會被忽略。

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

### 所有設定

| 設定 | 意思 | 沒寫的話 |
|---|---|---|
| `when` | 什麼時候跑，可以寫多行 | 只能手動跑 |
| `in` | 在哪個資料夾工作 | tasks 資料夾 |
| `run` | 代替 Claude Code 來做事的 shell 指令 | 由 Claude Code 來做 |
| `tools` | Claude 不用問就能做的事。`none` 表示都不允許。不能和 `run` 一起用 | `Read, Grep, Glob` |
| `model` | 用哪個 Claude 模型。不能和 `run` 一起用 | 你的 Claude Code 預設值 |
| `cooldown` | 跑完後多久內不再觸發 | `5h` |
| `timeout` | 跑超過這個時間就中止 | `1h` |
| `enabled` | 設成 `false` 就停用這個 task | `true` |

### `run:` 的指令會收到什麼

| 項目 | 內容 |
|---|---|
| 標準輸入 | 設定下面的文字 |
| 工作目錄 | `in:` 後面的資料夾 |
| `DOGGYBAG_TASK` | task 的檔名 |
| `DOGGYBAG_REASON` | 觸發的原因 |
| `DOGGYBAG_5H_REMAINING`、`DOGGYBAG_WEEK_REMAINING` | 剩餘 % |
| `DOGGYBAG_5H_RESETS_AT`、`DOGGYBAG_WEEK_RESETS_AT` | 重置時間（epoch 秒） |
| `DOGGYBAG_LOG` | 這次執行的 log 檔路徑 |

指令用 exit code 回報結果：`0` 是完成，`75` 是「現在沒事可做」（不算失敗，也不進 cooldown），其他是失敗。

指令印出的所有內容會寫到 `~/.doggybag/logs/`。

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

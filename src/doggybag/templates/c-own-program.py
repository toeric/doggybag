#!/usr/bin/env python3
# doggybag:
#   when: week.resets_in <= 1d and week.remaining >= 40
#   cooldown: 1d

"""範本 C：呼叫你自己的程式。

注意：只有透過已登入的 `claude` 指令跑的東西才會用到訂閱額度。
用 API key 的程式是另外計費的，doggybag 觸發它並不會用掉剩下的額度。

doggybag 會傳入這些環境變數：
  DOGGYBAG_TASK             這個 task 的檔名
  DOGGYBAG_REASON           觸發的原因
  DOGGYBAG_5H_REMAINING     5 小時窗口剩餘 %
  DOGGYBAG_WEEK_REMAINING   週額度剩餘 %
  DOGGYBAG_5H_RESETS_AT     5 小時窗口 reset 的時間（epoch 秒，窗口未開始時沒有）
  DOGGYBAG_WEEK_RESETS_AT   週額度 reset 的時間（epoch 秒）

結束時的 exit code：
  0     完成
  75    現在沒事可做（不算失敗，也不會進入 cooldown）
  其他  失敗

額度低於保留線或超過 timeout 時，doggybag 會送 SIGTERM，30 秒後還沒結束就強制停止。
"""

import os
import sys

remaining = int(os.environ.get("DOGGYBAG_WEEK_REMAINING", "0"))
print(f"triggered because: {os.environ.get('DOGGYBAG_REASON')}")
print(f"weekly quota left: {remaining}%")

# 在這裡呼叫你自己的 agent
sys.exit(75)

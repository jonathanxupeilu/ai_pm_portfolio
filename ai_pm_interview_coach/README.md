# AI 产品经理面试出题教练

脚本只做确定性的活；搜索、出题、判分由会话里的 AI 做。

## 一轮怎么用

    python scripts/resume.py                      # 读在线简历，我据此出题的靶子
    python scripts/bank.py sample --fresh         # 抽本轮题（只出 id）
    python scripts/bank.py show <id>              # 看题面和参考答案
    # 我作答 → AI 搜索面经、出题、判分
    echo '{"qid":"<id>","answer":"…","verdict":"部分对","feedback":"…"}' \
      | python scripts/attempts.py record         # 留痕
    python scripts/attempts.py weak               # 现在哪几题还不行

## 加真题

    echo '{"question":"…","refAnswer":"…","kind":"简历深挖","source":"…"}' \
      | python scripts/bank.py add

同指纹（同题面）会**拒绝且不覆盖**，所以导入可以重复跑。

## 三个退出码约定

- `0` 有结果
- `1` 没结果或输入不合法（「没抽到题」不是成功）
- stderr 永远说清是哪个文件、第几行、什么字段、期望什么

## 令牌

只从 `~/.workbuddy/mcp.json` 读，只读 `my-resume`，不落盘、不打印、不进 git。

# AGENTS.md

This file provides guidance to the AI agent when working with code in this repository.

本目录是新建项目，目前没有代码。这份文件**只记录本机/本仓库特有、不写就一定会踩**的几条；
产品设计、目录结构、运行命令等定下来之后再补，现在写了也只是猜。

## 怎么跑 Python

本机 `python` / `python3` 是 WindowsApps 假壳（退出码 49、零输出），`py` 不在 PATH。
**一律用**：`uv run --no-project python <脚本>`（需要时前缀 `PYTHONUTF8=1`）。
脚本只用标准库——加第三方依赖前先问，别默认 `pip install`。

## 令牌（红线）

猎聘令牌只从 `~/.workbuddy/mcp.json` 读（`mcpServers.liepin-mcp.headers.x-user-token`）。
**只读、不复制、不落盘、不打印、不进 git。** 配置缺失要显式报错退出，不许降级猜测。
也不要以「方便调试」为名把令牌打进任何输出。

## 真实数据不进版本库

本目录在 `ai_pm_portfolio` 仓库内（仓库根是上一层），而 `job_seeking/.gitignore` 只管它自己。
所以新脚本开始写某个真实数据文件（含真实公司名/岗位名/链接等）时，
**同一次改动里**在本目录加一份 `.gitignore` 把它挡掉。
真实数据在这个工作区常常是**唯一一份**：要腾空间或改动前，先整目录拷到仓库外再动手。

## 别做的事

- **绝不要在仓库内任何位置跑 `git clean -fdx` / `git clean -fdX`。** 这是唯一会删掉真实数据的
  git 命令；仓库根是 `ai_pm_portfolio`，在根目录跑同样会删掉 `job_seeking/` 下的数据。
  要看那些被忽略的文件用 `git status --ignored`，不要清理它们。

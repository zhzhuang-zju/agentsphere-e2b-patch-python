# agentsphere-e2b-patch

给官方 [E2B Python SDK](https://pypi.org/project/e2b/) 打补丁，目前的 patch 内容有：

- 让访问 envd（端口 **49983**）的请求自动带上 create sandbox 返回的 `traffic_access_token`。

## 安装

先直接分发 patch 文件，后续再考虑发布到 PyPI。使用 pip 命令安装：

```bash
# 安装 e2b 
pip install e2b
# 安装 agentsphere 的 e2b patch, 注意修改为实际版本
pip install ./agentsphere_e2b_patch-0.1.0-py3-none-any.whl
```

使用方式同普通 E2B SDK：

```python
from e2b import Sandbox

sandbox = Sandbox.create(...) 
```

如果是 editable 安装（`pip install -e .`）或环境禁用了 `.pth`，需要显式导入：

```python
import agentsphere_e2b_patch
from e2b import Sandbox

sandbox = Sandbox.create(...) 
```

## 非 envd 端口

如果不是通过 E2B SDK 访问 ENVD，比如访问 Sandbox 中启动的监听于 8080 的端口的应用进程： `https://{sandbox.get_host(8080)}` 。

由于 patch 不会去全局劫持 `httpx`，需要手工添加 traffic access token 的 header ，patch 提供了帮助函数 traffic_headers() ：

```python
import httpx
from agentsphere_e2b_patch import traffic_headers，

httpx.get(f"https://{sandbox.get_host(8080)}", headers=traffic_headers(sandbox))
```

> 备注： E2B 官方 SDK 也不会自动设置 traffic access token 的 header，同样需要用户手工设置。

## 开发

安装依赖的 build 和 pytest 包：

```bash
pip install build pytest
```

通过 Makefile 定义的 make 命令进行开发：

```bash
# 在  dist/  目录你下构建出 wheel 文件：python -m build
make build

# 开发安装：pip install -e ".[dev]"
make install

# 执行 pytest
make test

# 清理构建产物
make clean
```

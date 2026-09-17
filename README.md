# agentsphere-e2b-patch

给官方 [E2B Python SDK](https://pypi.org/project/e2b/) 打补丁，目前的 patch 内容有：

- 为访问 envd（端口 **49983**）的请求自动带上 e2b-traffic-access-token header，值来自 create sandbox 或者 connect sandbox 时返回的 `traffic_access_token`。
- 为访问 envd（端口 **49983**）之外的其他数据面请求提供帮助函数，方便设置 e2b-traffic-access-token header
- 为 E2B template start build 增加非原生的 `outboundNetwork`、`invoke`、`agencies`、`ping`、`observability`、`sessionStorageConfig` 和 `storageConfig` 请求字段

## 安装

先分发 patch 文件，后续再考虑发布到 PyPI。

为了方便下载，打包好的 patch 文件暂时存放在 dist 目录下。安装前请先下载 agentsphere_e2b_patch-xxx-py3-none-any.whl 文件到本地。

使用 pip 命令安装：

```bash
# 安装 e2b ：agentsphere-e2b-patch 只是 patch，官方 SDK 是必须的
pip install e2b
# 安装 agentsphere 的 e2b patch, 注意修改为实际版本
pip install ./agentsphere_e2b_patch-0.1.0-py3-none-any.whl
```

使用方式同普通 E2B SDK，正常情况下 agentsphere patch 会自动生效，对用户代码没有侵入：

```python
from e2b import Sandbox

sandbox = Sandbox.create(...) 
```

构建 template 时可以通过额外的 snake_case 参数设置 Agentsphere 的扩展字段。下面是一个完整示例：

```python
# 如果通过 wheel 安装且 Python 会自动加载 .pth 文件，这一行可以省略。
import agentsphere_e2b_patch

from e2b import Template

template = (
	Template()
	.from_image("python:3.11-slim")
	.run_cmd("pip install fastapi uvicorn")
	.run_cmd("mkdir -p /app")
	.copy("app.py", "/app/app.py")
	.set_start_cmd(
		"uvicorn app:app --host 0.0.0.0 --port 8080",
		"curl --fail http://localhost:8080/health",
	)
)

build = Template.build(
	template,
	name="my-template",
	outbound_network={
		"isPrivateConnect": True,
		"targetProjectId": "project-id",
		"targetVpcId": "vpc-id",
		"targetSubnetId": "subnet-id",
		"targetSecurityGroupIds": "sg-id",
	},
	invoke={
		"protocol": "http",
		"port": 8080,
	},
	agencies={
		"runtimeAgency": "my-agency",
	},
	ping={
		"enabled": True,
		"path": "/health",
		"protocol": "http",
		"port": 8080,
		"warmUpProbe": {
			"initialDelaySeconds": 1,
			"timeoutSeconds": 5,
			"periodSeconds": 2,
			"failureThreshold": 10,
		},
		"livenessProbe": {
			"periodSeconds": 10,
			"timeoutSeconds": 5,
			"failureThreshold": 3,
		},
	},
	observability={
		"logs": {
			"enableStdLogs": True,
			"ltsProjectId": "logs-project-id",
			"ltsGroupId": "logs-group-id",
			"ltsStreamId": "logs-stream-id",
		},
		"metrics": {
			"enableSystemMetrics": True,
			"aomProjectId": "aom-project-id",
			"aomInstanceId": "aom-instance-id",
		},
		"relabeling": {
			"rules": [],
		},
	},
	session_storage_config={
		"mountDir": "/mnt/session",
	},
	storage_config={
		"obsMounts": [
			{
				"bucket": "my-bucket",
				"bucketPath": "templates/data",
				"mountDir": "/mnt/obs",
				"readOnly": True,
			}
		],
		"sfsTurboMounts": [
			{
				"sfsTurboId": "sfs-turbo-id",
				"shareRoot": "/",
				"sharePath": "/templates/data",
				"mountDir": "/mnt/sfs",
				"readOnly": False,
				"withSessionCredential": True,
			}
		],
	},
)

print(f"template build started: {build}")
```

这些字段在 Python 中使用 snake_case 参数名，例如 `outbound_network`、
`session_storage_config` 和 `storage_config`，patch 会将它们转换为请求体中的
JSON 字段名。`Template.build_in_background` 以及异步 SDK 的对应方法也支持同样的参数。

但如果是 editable 安装（`pip install -e .`）或环境禁用了 `.pth`，就需要增加导入的代码：

```python
# 增加这样 import 代码，要在 e2b from 语句前
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

> 备注： E2B 官方 SDK 不会自动设置 traffic access token 的 header，同样需要用户手工设置。

## 开发

构建前先安装依赖的 build 和 pytest 包：

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

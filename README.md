# 离线双端消息协议分析 API

基于 Python + FastAPI，对 A、B 两端的 send/receive 状态机做离线可达性分析，包括死锁检测、完成保证、完成计划与最小停用方案。服务完全离线运行，不依赖数据库或外部服务。

## 协议模型

- A、B 各有 1～8 个状态，一个初态和一个非空终态集。
- 每个转移包含：
  - `id`：全局唯一转移 ID；
  - `from`、`to`：端点，只能是 `A` 或 `B`，且不能相同；
  - `action`：`send` 或 `receive`；
  - `message`：消息类型；
  - `source`、`target`：执行该转移的端点状态。
- `send` 转移由 `from` 端点执行，向 `from -> to` 的一格队列写入消息。
- `receive` 转移由 `to` 端点执行，要求反方向队首消息等于 `message`，消费后队列变空。
- 每个方向只有一格队列：
  - 发送方向队列非空时不能发送；
  - 接收消息与队首不匹配时不能接收。
- 所有可执行转移可任意交错。
- 两端均处于终态且两个队列都为空时为“完成”，该配置不再扩展。
- 除完成配置外，其他配置没有任何可执行转移时即为死锁。
- 全局转移数不超过 30，不同消息种类不超过 8。

分析器使用 BFS 遍历全部可达配置。若存在死锁，第一条最短路径会被选中；同一长度下按转移 ID 序列的字典序选择。

## 单条命令启动

```bash
docker compose up --build -d
```

该命令会构建镜像并在后台启动服务。服务监听 **8000 端口**。

查看日志：

```bash
docker compose logs -f
```

- 健康检查：`GET http://localhost:8000/healthz`
- Swagger 文档：`http://localhost:8000/docs`
- OpenAPI：`http://localhost:8000/openapi.json`

如使用旧版 Docker Compose，可运行：

```bash
docker-compose up --build
```

## 调用示例

### 存在死锁

```bash
curl -X POST http://localhost:8000/v1/deadlocks \
  -H 'Content-Type: application/json' \
  -d '{
    "A": {
      "states": [0, 1],
      "initial": 0,
      "finals": [1]
    },
    "B": {
      "states": [0, 1],
      "initial": 0,
      "finals": [1]
    },
    "transitions": [
      {
        "id": "t1",
        "from": "A",
        "to": "B",
        "action": "send",
        "message": "m",
        "source": 0,
        "target": 1
      },
      {
        "id": "t2",
        "from": "B",
        "to": "A",
        "action": "send",
        "message": "x",
        "source": 0,
        "target": 1
      },
      {
        "id": "t3",
        "from": "B",
        "to": "A",
        "action": "receive",
        "message": "x",
        "source": 0,
        "target": 1
      },
      {
        "id": "t4",
        "from": "A",
        "to": "B",
        "action": "receive",
        "message": "m",
        "source": 0,
        "target": 1
      }
    ]
  }'
```

示例响应：

```json
{
  "deadlock": true,
  "visited_states": 5,
  "initial": {
    "state": { "A": 0, "B": 0 },
    "queues": { "A_to_B": null, "B_to_A": null }
  },
  "deadlock_state": {
    "state": { "A": 1, "B": 1 },
    "queues": { "A_to_B": "m", "B_to_A": "x" }
  },
  "path": [
    {
      "index": 1,
      "transition_id": "t1",
      "from": "A",
      "to": "B",
      "action": "send",
      "message": "m",
      "state": { "A": 1, "B": 0 },
      "queues": { "A_to_B": "m", "B_to_A": null }
    },
    {
      "index": 2,
      "transition_id": "t2",
      "from": "B",
      "to": "A",
      "action": "send",
      "message": "x",
      "state": { "A": 1, "B": 1 },
      "queues": { "A_to_B": "m", "B_to_A": "x" }
    }
  ]
}
```

`visited_states` 表示访问过的不同配置数；配置包含两端状态和两个队列内容。

### 无死锁时的响应

```json
{
  "deadlock": false,
  "visited_states": 1,
  "initial": {
    "state": { "A": "done", "B": "done" },
    "queues": { "A_to_B": null, "B_to_A": null }
  },
  "deadlock_state": null,
  "path": null
}
```

## 完成保证：`POST /v1/completion-guarantees`

接收与死锁分析**完全相同的协议请求**（不增加任何字段），对从初态出发、按一格队列规则产生的所有可执行转移交错做判定：

- 只有**每次运行都结束于完成配置**（两端均处终态且两个队列都为空，完成配置不再扩展）才算保证完成；
- 运行可能停在完成配置之外、且没有任何可执行转移的配置时，报告 **deadlock**；
- 否则存在可达配置位于有向环上、从而可以无限重复时，报告 **cycle**；即使该循环存在通往完成的出口，也必须报告；
- 死锁与循环并存时，优先报告死锁。

响应字段：

- `result`：`"guaranteed"`、`"deadlock"`、`"cycle"` 之一；
- `visited_states`：访问过的不同配置数（含完成配置）；
- `initial`：初态视图；
- `witness`：保证完成时为 `null`；否则为见证对象：
  - 死锁见证：`kind` 为 `"deadlock"`，`deadlock_state` 为死锁配置，`path` 是从初态到该配置的最短路径（同长度按转移 ID 序列字典序）；
  - 循环见证：`kind` 为 `"cycle"`，`entry_state` 为循环入口配置，`prefix` 是从初态到入口的路径（入口即初态时为 `[]`），`cycle` 是从入口出发并回到入口的非空循环。

`prefix` 与 `cycle` 中的每一步都逐步列出 `transition_id`、`from`、`to`、`action`、`message` 以及执行后的两端状态与队列；两部分各自从 `index: 1` 重新编号。

### 可执行调用示例：存在循环（且循环有通往完成的出口）

```bash
curl -X POST http://localhost:8000/v1/completion-guarantees \
  -H 'Content-Type: application/json' \
  -d '{
    "A": {
      "states": [0, 1],
      "initial": 0,
      "finals": [1]
    },
    "B": {
      "states": [0, 1],
      "initial": 0,
      "finals": [1]
    },
    "transitions": [
      {
        "id": "t1",
        "from": "A",
        "to": "B",
        "action": "send",
        "message": "m",
        "source": 0,
        "target": 0
      },
      {
        "id": "t2",
        "from": "A",
        "to": "B",
        "action": "receive",
        "message": "m",
        "source": 0,
        "target": 0
      },
      {
        "id": "t3",
        "from": "A",
        "to": "B",
        "action": "send",
        "message": "f",
        "source": 0,
        "target": 1
      },
      {
        "id": "t4",
        "from": "A",
        "to": "B",
        "action": "receive",
        "message": "f",
        "source": 0,
        "target": 1
      }
    ]
  }'
```

该协议在初态可反复执行 `t1, t2` 回到自身（无限运行），也可执行 `t3, t4` 到达完成配置；由于存在无限运行，结果为 `cycle`：

```json
{
  "result": "cycle",
  "visited_states": 4,
  "initial": {
    "state": { "A": 0, "B": 0 },
    "queues": { "A_to_B": null, "B_to_A": null }
  },
  "witness": {
    "kind": "cycle",
    "entry_state": {
      "state": { "A": 0, "B": 0 },
      "queues": { "A_to_B": null, "B_to_A": null }
    },
    "prefix": [],
    "cycle": [
      {
        "index": 1,
        "transition_id": "t1",
        "from": "A",
        "to": "B",
        "action": "send",
        "message": "m",
        "state": { "A": 0, "B": 0 },
        "queues": { "A_to_B": "m", "B_to_A": null }
      },
      {
        "index": 2,
        "transition_id": "t2",
        "from": "A",
        "to": "B",
        "action": "receive",
        "message": "m",
        "state": { "A": 0, "B": 0 },
        "queues": { "A_to_B": null, "B_to_A": null }
      }
    ]
  }
}
```

### 保证完成时的响应

例如只有一次发送并被消费的协议（A 经 `send` 到终态，B 经 `receive` 到终态）：

```json
{
  "result": "guaranteed",
  "visited_states": 3,
  "initial": {
    "state": { "A": 0, "B": 0 },
    "queues": { "A_to_B": null, "B_to_A": null }
  },
  "witness": null
}
```

### 死锁时的响应

存在死锁时（即使同时存在循环），`result` 为 `"deadlock"`，`witness.kind` 为 `"deadlock"`，并返回通往该配置的最短路径，例如本文开头死锁协议的响应：

```json
{
  "result": "deadlock",
  "visited_states": 5,
  "initial": {
    "state": { "A": 0, "B": 0 },
    "queues": { "A_to_B": null, "B_to_A": null }
  },
  "witness": {
    "kind": "deadlock",
    "deadlock_state": {
      "state": { "A": 1, "B": 1 },
      "queues": { "A_to_B": "m", "B_to_A": "x" }
    },
    "path": [
      {
        "index": 1,
        "transition_id": "t1",
        "from": "A",
        "to": "B",
        "action": "send",
        "message": "m",
        "state": { "A": 1, "B": 0 },
        "queues": { "A_to_B": "m", "B_to_A": null }
      },
      {
        "index": 2,
        "transition_id": "t2",
        "from": "B",
        "to": "A",
        "action": "send",
        "message": "x",
        "state": { "A": 1, "B": 1 },
        "queues": { "A_to_B": "m", "B_to_A": "x" }
      }
    ]
  }
}
```

## 带里程碑的完成计划：`POST /v1/completion-plans`

在原有协议请求的基础上增加可选字段 `required_transition_ids`（0～6 个**互异**的现有转移 ID，缺省为 `[]`）。服务在与死锁分析完全相同的可达空间中寻找一条路径，使得：

- 每个指定转移在路径中**至少执行一次**；
- 路径终点两端均处于终态且两个队列都为空（完成配置不再扩展）。

路径优先选择转移数最少的；长度相同时按转移 ID 序列的字典序取第一条。响应中的 `visited_combinations` 是访问过的不同「配置 × 已命中指定 ID 集合」组合数（同一配置经由不同已命中集合到达会分别计数）。

### 可执行调用示例

```bash
curl -X POST http://localhost:8000/v1/completion-plans \
  -H 'Content-Type: application/json' \
  -d '{
    "A": {
      "states": [0, 1],
      "initial": 0,
      "finals": [1]
    },
    "B": {
      "states": [0, 1],
      "initial": 0,
      "finals": [1]
    },
    "transitions": [
      {
        "id": "t1",
        "from": "A",
        "to": "B",
        "action": "send",
        "message": "m",
        "source": 0,
        "target": 1
      },
      {
        "id": "t2",
        "from": "B",
        "to": "A",
        "action": "send",
        "message": "x",
        "source": 0,
        "target": 1
      },
      {
        "id": "t3",
        "from": "B",
        "to": "A",
        "action": "receive",
        "message": "x",
        "source": 0,
        "target": 1
      },
      {
        "id": "t4",
        "from": "A",
        "to": "B",
        "action": "receive",
        "message": "m",
        "source": 0,
        "target": 1
      }
    ],
    "required_transition_ids": ["t1"]
  }'
```

存在满足条件的路径时（示例中最短路径为 `t1, t4`）：

```json
{
  "completable": true,
  "visited_combinations": 6,
  "initial": {
    "state": { "A": 0, "B": 0 },
    "queues": { "A_to_B": null, "B_to_A": null }
  },
  "path": [
    {
      "index": 1,
      "transition_id": "t1",
      "from": "A",
      "to": "B",
      "action": "send",
      "message": "m",
      "state": { "A": 1, "B": 0 },
      "queues": { "A_to_B": "m", "B_to_A": null }
    },
    {
      "index": 2,
      "transition_id": "t4",
      "from": "A",
      "to": "B",
      "action": "receive",
      "message": "m",
      "state": { "A": 1, "B": 1 },
      "queues": { "A_to_B": null, "B_to_A": null }
    }
  ]
}
```

无满足条件的路径时，`path` 为 `null`：

```json
{
  "completable": false,
  "visited_combinations": 4,
  "initial": {
    "state": { "A": 0, "B": 0 },
    "queues": { "A_to_B": null, "B_to_A": null }
  },
  "path": null
}
```

初态本身已满足条件时（例如 `required_transition_ids` 为空且两端已在终态、队列均空），`completable` 为 `true` 且 `path` 为 `[]`，`visited_combinations` 为 `1`。

## 最小停用方案：`POST /v1/deactivation-plans`

在原有协议请求的基础上增加可选字段 `removable_transition_ids`（0～8 个**互异**的现有转移 ID，缺省为 `[]`）。服务尝试停用其中若干转移，使修订后的协议满足：**从初态可达的每个配置都存在一条通往完成配置的路径**（即使不存在死锁，只要存在无法到达完成的可达配置，该方案也不合格）。只允许停用列表内的转移。

对每个候选方案，服务按原有一格队列语义重建可达图（完成配置不再扩展），并检查全部可达配置是否都能到达完成。方案选择规则：

1. 停用转移数最少者优先；
2. 数量相同时，按升序 ID 列表的字典序取第一个。

响应字段：

- `solvable`：是否存在合格的停用方案；
- `deactivated_transition_ids`：停用的转移 ID 升序列表；原协议本身已合格时为 `[]`，无方案时为 `null`；
- `reachable_configurations`：修订后从初态可达的配置数（含完成配置），无方案时为 `null`。

### 可执行调用示例

```bash
curl -X POST http://localhost:8000/v1/deactivation-plans \
  -H 'Content-Type: application/json' \
  -d '{
    "A": {
      "states": [0, 1],
      "initial": 0,
      "finals": [1]
    },
    "B": {
      "states": [0, 1],
      "initial": 0,
      "finals": [1]
    },
    "transitions": [
      {
        "id": "t1",
        "from": "A",
        "to": "B",
        "action": "send",
        "message": "m",
        "source": 0,
        "target": 1
      },
      {
        "id": "t2",
        "from": "A",
        "to": "B",
        "action": "receive",
        "message": "m",
        "source": 0,
        "target": 1
      },
      {
        "id": "t3",
        "from": "A",
        "to": "B",
        "action": "send",
        "message": "z",
        "source": 0,
        "target": 0
      }
    ],
    "removable_transition_ids": ["t3"]
  }'
```

示例中 `t3` 发出的 `z` 消息无人接收，会让协议进入死锁配置；停用 `t3` 后所有可达配置都能完成：

```json
{
  "solvable": true,
  "deactivated_transition_ids": ["t3"],
  "reachable_configurations": 3
}
```

同一请求去掉 `removable_transition_ids`（缺省为 `[]`，即不允许停用任何转移）时无合格方案：

```json
{
  "solvable": false,
  "deactivated_transition_ids": null,
  "reachable_configurations": null
}
```

## 请求校验与 422

以下情况返回 HTTP `422 Unprocessable Entity`：

- 状态集数量不在 1～8；
- 终态集为空、数量超过 8 或包含重复值；
- 初态或终态非法引用；
- 转移的 `source` 或 `target` 不属于执行端点的状态集；
- 转移 ID 重复；
- 转移数量超过 30；
- 不同消息种类超过 8；
- `from`、`to`、`action` 取值非法，或两端相同；
- 请求中出现未定义字段、空 ID/消息等越界输入。

`POST /v1/completion-guarantees` 直接复用上述通用校验（请求体与死锁分析完全一致，不接受额外字段）。

`POST /v1/completion-plans` 在上述规则之外，以下情况同样返回 `422 Unprocessable Entity`：

- `required_transition_ids` 中出现请求未定义的转移 ID；
- `required_transition_ids` 中包含重复 ID；
- `required_transition_ids` 数量超过 6（或包含空 ID）。

`POST /v1/deactivation-plans` 在通用规则之外，以下情况同样返回 `422 Unprocessable Entity`：

- `removable_transition_ids` 中出现请求未定义的转移 ID；
- `removable_transition_ids` 中包含重复 ID；
- `removable_transition_ids` 数量超过 8（或包含空 ID）。

## 本地开发（不使用 Docker）

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 项目结构

```text
.
├── app/
│   ├── __init__.py
│   ├── analyzer.py
│   ├── main.py
│   └── schemas.py
├── Dockerfile
├── docker-compose.yml
├── README.md
└── requirements.txt
```

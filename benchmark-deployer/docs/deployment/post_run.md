# 벤치마크 실행

# API 설계

**HTTP Method:** `POST`

**API Path:** `/run`

**Content-Type:** `application/json`

## 동작

벤치마크를 실행합니다. 다음은 벤치마크를 실행하기 위한 매니페스트 YAML 을 생성하는 과정입니다.

1. Benchmark Manager 에 `GET /projects/{project_id}/files` 를 요청하여, 프로젝트의 파일 목록을 가져옵니다.
2. 프로젝트의 파일 목록에서 벤치마크 Job 파일 (`.yaml`) 과 Config 파일 (`.json`) 을 가져옵니다.
   - `file_type` 이 `"job` 이면 Job, `"config"` 이면 Config 입니다.
   - `benchmark_type` 과 `file_id` 로 Job 또는 Config 파일의 내용 (`content`)을 가져옵니다.
3. 프로젝트에서 벤치마크 Job 파일 (`.yaml`) 과 Config 파일 (`.json`) 을 가져옵니다.
   - Benchmark Manager 에 `GET /projects/{project_id}/files` 를 요청합니다.
   - 응답 데이터에서 `benchmark_type` 과 `file_id` 로 Job 파일 (`file_type: "job"`) 의 `content` 를 가져옵니다.
   - 응답 데이터에서 `benchmark_type` 과 `file_id` 로 Config 파일의 `contents` 를 가져옵니다.
4. Job 매니페스트에 Config JSON 를 `ConfigMap` 으로 `/app/configs/eval_config.json` 경로에 마운트합니다.
5. Job 의 `env` 에 `VLLM_MODEL_ENDPOINT` 이름으로 vLLM 모델의 엔드포인트를 설정합니다.

## 요청

| Property              | Description             | Type     | Required |
| --------------------- | ----------------------- | -------- | -------- |
| `project_id`          | 프로젝트 ID             | `string` | `true`   |
| `benchmark_type`      | 벤치마크 타입           | `string` | `true`   |
| `name`                | 벤치마크 이름           | `string` | `true`   |
| `job_file_id`         | 벤치마크 Job 파일 ID    | `string` | `true`   |
| `config_file_id`      | 벤치마크 Config 파일 ID | `string` | `false`  |
| `vllm_model_endpoint` | vLLM 모델의 엔드포인트  | `string` | `false`  |

### 예시 데이터

```json
{
  "project_id": "bc8a1ab7-e65e-4126-80de-488ace7a8973",
  "benchmark_type": "evalchemy",
  "name": "evalchemy-1755046868150",
  "job_file_id": "1a4e797c-d1cf-44fb-ba3b-ca2ca5266e0d",
  "config_file_id": "b9f05016-d73a-413f-930b-2f3625b62a8a",
  "vllm_model_endpoint": "http://vllm-qwen3-30b.vllm:8000/v1/completions"
}
```

## 응답

### `200 OK`

> 실행 요청이 성공한 경우

| Property        | Description                     | Type     | Required |
| --------------- | ------------------------------- | -------- | -------- |
| `deployment_id` | 벤치마크 배포 ID                | `string` | `true`   |
| `status`        | 벤치마크 실행 상태              | `string` | `true`   |
| `resource_type` | 벤치마크 실행 리소스 타입       | `string` | `true`   |
| `resource_name` | 벤치마크 실행 리소스 이름       | `string` | `true`   |
| `namespace`     | 벤치마크 실행 네임스페이스      | `string` | `true`   |
| `yaml_content`  | 벤치마크 리소스 매니페스트 YAML | `string` | `true`   |
| `message`       | 메시지                          | `string` | `true`   |
| `created_at`    | 등록 시간 (`date-time` 포맷)    | `string` | `true`   |

- `status` 는 다음의 값 중 하나 입니다.
  - `"pending"`
  - `"running"`
  - `"completed"`
  - `"failed"`
  - `"deleted"`
- `resource_type` 은 다음의 값 중 하나 입니다.
  - `"job"`
  - `"deployment"`
  - `"service"`
  - `"configmap"`
  - `"secret"`
  - `"unknown"`

### `400 Bad Request`

> 요청 데이터가 잘못된 경우

| Property | Description | Type     | Required |
| -------- | ----------- | -------- | -------- |
| `detail` | 에러 메시지 | `string` | `true`   |

### `422 Unprocessable Content`

> 요청 데이터 유효성 검사에 실패한 경우

### `500 Internal Server Error`

> 서버에 에러가 발생한 경우

| Property | Description | Type     | Required |
| -------- | ----------- | -------- | -------- |
| `detail` | 에러 메시지 | `string` | `true`   |

# OpenAPI Specification

```json
{
  "openapi": "3.0.3",
  "info": {
    "title": "Benchmark Deployer API",
    "version": "1.0.0",
    "description": "벤치마크 배포 및 실행을 위한 REST API"
  },
  "servers": [
    {
      "url": "http://localhost:8000",
      "description": "Development server"
    }
  ],
  "paths": {
    "/run": {
      "post": {
        "summary": "벤치마크 실행",
        "description": "Config와 vLLM 모델의 엔드포인트와 함께 벤치마크를 실행합니다.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/BenchmarkRunRequest"
              },
              "example": {
                "project_id": "bc8a1ab7-e65e-4126-80de-488ace7a8973",
                "benchmark_type": "evalchemy",
                "name": "evalchemy-1755046868150",
                "job_file_id": "1a4e797c-d1cf-44fb-ba3b-ca2ca5266e0d",
                "config_file_id": "b9f05016-d73a-413f-930b-2f3625b62a8a",
                "vllm_model_endpoint": "http://vllm-qwen3-30b.vllm:8000/v1/completions"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "벤치마크 실행 요청 성공",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/BenchmarkRunResponse"
                }
              }
            }
          },
          "400": {
            "description": "요청 데이터가 잘못된 경우",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "요청 데이터 유효성 검사에 실패한 경우",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "500": {
            "description": "서버에 에러가 발생한 경우",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "BenchmarkRunRequest": {
        "type": "object",
        "description": "벤치마크 실행 요청을 위한 스키마",
        "required": [
          "project_id",
          "benchmark_type",
          "name",
          "job_file_id",
          "config_file_id"
        ],
        "properties": {
          "project_id": {
            "type": "string",
            "description": "프로젝트 ID",
            "format": "uuid",
            "example": "bc8a1ab7-e65e-4126-80de-488ace7a8973"
          },
          "benchmark_type": {
            "type": "string",
            "description": "벤치마크 타입",
            "example": "evalchemy"
          },
          "name": {
            "type": "string",
            "description": "벤치마크 이름",
            "example": "evalchemy-1755046868150"
          },
          "job_file_id": {
            "type": "string",
            "description": "벤치마크 Job 파일 ID",
            "format": "uuid",
            "example": "1a4e797c-d1cf-44fb-ba3b-ca2ca5266e0d"
          },
          "config_file_id": {
            "type": "string",
            "description": "벤치마크 Config 파일 ID",
            "format": "uuid",
            "example": "b9f05016-d73a-413f-930b-2f3625b62a8a"
          },
          "vllm_model_endpoint": {
            "type": "string",
            "description": "vLLM 모델의 엔드포인트",
            "format": "uri",
            "example": "http://vllm-qwen3-30b.vllm:8000/v1/completions"
          }
        },
        "additionalProperties": false
      },
      "BenchmarkRunResponse": {
        "type": "object",
        "description": "벤치마크 실행 성공 응답을 위한 스키마",
        "required": [
          "deployment_id",
          "status",
          "resource_type",
          "resource_name",
          "namespace",
          "yaml_content",
          "message",
          "created_at"
        ],
        "properties": {
          "deployment_id": {
            "type": "string",
            "description": "벤치마크 배포 ID",
            "example": "benchmark-deployment-12345"
          },
          "status": {
            "type": "string",
            "description": "벤치마크 실행 상태",
            "enum": ["pending", "running", "completed", "failed", "deleted"],
            "example": "pending"
          },
          "resource_type": {
            "type": "string",
            "description": "벤치마크 실행 리소스 타입",
            "enum": [
              "job",
              "deployment",
              "service",
              "configmap",
              "secret",
              "unknown"
            ],
            "example": "job"
          },
          "resource_name": {
            "type": "string",
            "description": "벤치마크 실행 리소스 이름",
            "example": "benchmark-job-evalchemy-1755046868150"
          },
          "namespace": {
            "type": "string",
            "description": "벤치마크 실행 네임스페이스",
            "example": "benchmark"
          },
          "yaml_content": {
            "type": "string",
            "description": "벤치마크 리소스 매니페스트 YAML",
            "example": "apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: benchmark-job..."
          },
          "message": {
            "type": "string",
            "description": "메시지",
            "example": "벤치마크가 성공적으로 배포되었습니다."
          },
          "created_at": {
            "type": "string",
            "description": "등록 시간 (date-time 포맷)",
            "format": "date-time",
            "example": "2024-01-15T10:30:00Z"
          }
        },
        "additionalProperties": false
      },
      "ErrorResponse": {
        "type": "object",
        "description": "에러 응답을 위한 스키마",
        "required": ["detail"],
        "properties": {
          "detail": {
            "type": "string",
            "description": "에러 메시지",
            "example": "잘못된 요청 데이터입니다."
          }
        },
        "additionalProperties": false
      }
    }
  }
}
```

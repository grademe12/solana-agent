# Agentic Checkout

QR·결제 링크를 기계 판독 가능한 결제 의도로 변환하고, Gemini 기반 에이전트가 사전 정책과 예산 범위 안에서 Solana 스테이블코인 결제를 실행하는 해커톤 프로젝트입니다.

현재 저장소는 P0 결제 코어, ADK 실행 경로, 웹 데모까지 구현된 상태입니다. 실제
Devnet E2E에는 Google Cloud 인증과 테스트 SOL·USDC가 필요합니다.

- [구현 계획](docs/implementation-plan.md)
- [의존성 패키지 역할과 관계](docs/dependencies.md)
- [Solana Devnet 지갑 및 테스트 자산 준비](docs/devnet-setup.md)
- [Cloud Run 배포 가이드](docs/cloud-run-deployment.md)

## 로컬 개발 환경

필수 런타임:

- Python 3.12
- Node.js 20.9 이상
- pnpm 11

### Python API

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "pip<26.2"
.\.venv\Scripts\python.exe -m pip install pip-tools
.\.venv\Scripts\pip-compile.exe --extra dev --strip-extras -o requirements.lock pyproject.toml
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe scripts\verify_environment.py
.\.venv\Scripts\python.exe -m pytest
```

### Web

```powershell
pnpm install --frozen-lockfile
pnpm build:web
pnpm dev:web
```

실제 Gemini·Solana 연결 전에 `.env.example`을 `.env`로 복사하고 필요한 값만 로컬에서
설정합니다. 비밀키와 실제 자격 증명은 Git에 추가하지 않습니다.

### API 컨테이너

루트 `Dockerfile`은 Cloud Run용 agent API 이미지를 정의한다. Docker가 설치된
환경에서는 다음으로 로컬 이미지를 검증할 수 있다.

이미지는 테스트·린트 도구를 제외한 `requirements.runtime.lock`을 사용한다.

```powershell
docker build -t agentic-checkout-api .
docker run --rm -p 8080:8080 agentic-checkout-api
```

기본 실행 모드는 `mock`이며 실제 키 파일을 이미지에 복사하지 않는다.

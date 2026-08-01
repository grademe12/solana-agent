# Agentic Checkout

QR·결제 링크를 기계 판독 가능한 결제 의도로 변환하고, Gemini 기반 에이전트가 사전 정책과 예산 범위 안에서 Solana 스테이블코인 결제를 실행하는 해커톤 프로젝트입니다.

현재 저장소는 P0 구현 환경 구성 단계입니다.

- [구현 계획](docs/implementation-plan.md)
- [의존성 패키지 역할과 관계](docs/dependencies.md)
- [Solana Devnet 지갑 및 테스트 자산 준비](docs/devnet-setup.md)

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

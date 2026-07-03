# infrastructure-design.md — U3 Accounts AWS 리소스 및 보안 명세서

**단계**: CONSTRUCTION → Infrastructure Design (유닛별 루프, Track 2 첫 유닛) · **유닛**: U3 Accounts · **일자**: 2026-06-16
**근거(SSOT)**: `construction/plans/u3-accounts-infrastructure-design-plan.md` (Q1~Q5 답변 반영)

---

## 1. AWS 데이터베이스 및 스토리지 리소스 명세

### 1.1. Amazon RDS PostgreSQL (사용자 및 자격증명 저장소)
계정 도메인 엔티티 및 자격증명 해시 데이터 보관을 위한 주 RDBMS 사양입니다 (Q2 반영).
- **리소스 사양**:
  - **인스턴스 클래스**: `db.t4g.small` (2 vCPU, 2 GB RAM - AWS Graviton3 기반)
  - **엔진 버전**: PostgreSQL `16.x`
  - **스토리지**: `20 GB` gp3 (General Purpose SSD, 최대 3,000 IOPS 및 125 MB/s 처리량 보장)
  - **다중 가용 영역(Multi-AZ)**: **활성화 (Enabled)** - 장애 발생 시 다른 AZ의 대기 인스턴스로 자동 페일오버 수행
  - **백업 정책**: 자동 백업 활성화 (보존 기간 7일, 매일 정기 스냅샷 생성 - RPO < 24시간)

### 1.2. Amazon ElastiCache Redis (인메모리 세션 스토리지)
극도로 낮은 세션 조회 레이턴시(P50 < 5ms) 및 세션 유지 가용성을 위한 Redis 복제본 클러스터 구성입니다 (Q3 반영).
- **리소스 사양**:
  - **노드 타입**: `cache.t4g.micro` (0.5 GB RAM)
  - **엔진 버전**: Redis `7.x`
  - **노드 토폴로지**: **기본 노드(Primary) 1개 + 복제 노드(Replica) 1개** (총 2개 노드 구성)
  - **다중 가용 영역(Multi-AZ)**: **활성화 (Enabled)** - 기본 노드 장애 감지 시 복제본 노드로 자동 페일오버 (RTO < 1분, RPO = 0)

---

## 2. 외부 통합 및 연동 인프라

### 2.1. Resend (이메일 발송 서비스, 기존 Amazon SES → Resend 전환 완료)
PENDING 계정 이메일 활성화 인증 링크 발송을 위한 이메일 인프라입니다 (Q5 반영).
- **자격증명 검증 방식**: **도메인 인증 (Domain Verification)**
  - Route 53 DNS 존에 Resend가 제공하는 DKIM CNAME 레코드 및 SPF(TXT) 레코드를 바인딩하여 도메인 전체 발송 권한을 확보하고 수신 차단을 예방합니다.
  - **발송 한도**: Resend는 SES와 같은 샌드박스 해제 요청 절차가 없으며, 도메인 검증 완료 후 프로덕션 발송이 활성화됩니다.

### 2.2. Google reCAPTCHA v3 (인프라 구성 요소)
- **자격증명**: AWS Secrets Manager(또는 Parameter Store)에서 안전하게 변수를 관리하며, 배포 정의(Deployment Task Definition) 단계에서 컨테이너 OS 환경변수로 안전하게 투과 주입됩니다.

---

## 3. 네트워크 보안 그룹(Security Group) 규칙 명세

네트워크 레이어에서 데이터 저장소 접근을 완전히 격리하기 위한 최소 권한(Least Privilege) 규칙입니다 (Q4 반영).

```
[인터넷] ──(80/443)──> [Application Load Balancer] (ALB-SG)
                             | (80/443)
                             v
                       [ECS Fargate] (ECS-SG, 퍼블릭 서브넷 배치)
                        /         \
                 (TCP 5432)     (TCP 6379)
                      /             \
                     v               v
             [RDS PostgreSQL]   [ElastiCache Redis]
                (RDS-SG)            (Redis-SG)
             (격리 서브넷 배치)    (격리 서브넷 배치)
```

### 3.1. ALB-SG (로드밸런서 보안 그룹)
- **인바운드**: `0.0.0.0/0` (모든 IP)에 대해 TCP Port `80`(HTTP) 및 `443`(HTTPS) 허용.
- **아웃바운드**: `ECS-SG` 방향으로 HTTP/HTTPS 허용.

### 3.2. ECS-SG (컴퓨트 Fargate 보안 그룹)
- **인바운드**: `ALB-SG`로부터의 TCP Port `80` 및 `443` 진입만 허용.
- **아웃바운드**:
  - `RDS-SG` 방향으로 TCP Port `5432` 허용.
  - `Redis-SG` 방향으로 TCP Port `6379` 허용.
  - 인터넷(`0.0.0.0/0`) 방향으로 TCP Port `443` 허용 (Resend, Google reCAPTCHA, 외부 RAG 검색 API 호출 용도).

### 3.3. RDS-SG (데이터베이스 보안 그룹)
- **인바운드**: 오직 `ECS-SG` 보안 그룹의 사설 IP 대역으로부터의 TCP Port `5432` 진입만 허용 (퍼블릭 인그레스 차단).
- **아웃바운드**: 없음 (기본 Deny).

### 3.4. Redis-SG (인메모리 캐시 보안 그룹)
- **인바운드**: 오직 `ECS-SG` 보안 그룹의 사설 IP 대역으로부터의 TCP Port `6379` 진입만 허용.
- **아웃바운드**: 없음.

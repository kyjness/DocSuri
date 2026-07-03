# deployment-architecture.md — U3 Accounts 배포 아키텍처 및 VPC 토폴로지 설계서

**단계**: CONSTRUCTION → Infrastructure Design (유닛별 루프, Track 2 첫 유닛) · **유닛**: U3 Accounts · **일자**: 2026-06-16
**근거(SSOT)**: `construction/plans/u3-accounts-infrastructure-design-plan.md` (Q1~Q5 답변 반영)

---

## 1. 컴퓨트 아키텍처 및 Fargate 사양 (Q1 반영)

U2/U3/U4/U6-미들웨어가 하나로 패키징되는 API 모듈형 모놀리스 배포 단위 ①의 ECS Fargate 명세입니다.
- **컴퓨트 서비스**: **AWS ECS Fargate** (상시 가동 런타임, 콜드 스타트 제거)
- **부하 분산**: Application Load Balancer (ALB) 후면에 배치하여 외부 HTTPS 요청을 ECS Fargate 태스크로 분산합니다.
- **태스크 정의 (Task Definition) 사양**:
  - **CPU**: `0.25 vCPU` (256 CPU Units - Fargate 최소 사양, 비용 최적화)
  - **Memory**: `512 MB` (Fargate 최소 사양, 비용 최적화)
  - **기동 태스크 수**: 최소 `1` ~ 최대 `2` (가용성 가드레일 제공 및 월 구동비 최적화)
  - **컨테이너 이미지**: `Dockerfile` 기반 빌드 후 ECR에 업로드하여 이미지 다이제스트 해시로 버전을 고정합니다 (SEC-10).

---

## 2. 물리 네트워크 토폴로지 (VPC & Subnets, Q4 반영)

NAT Gateway 고정 비용(월 $64/2 AZ 기준)을 절감하면서 데이터베이스 계층의 격리 보안 표준을 준수하기 위해 **NAT Gateway를 배제한 하이브리드 VPC 네트워크**를 디자인합니다.

```
VPC (CIDR: 10.0.0.0/16, ap-northeast-2 리전)
├── Public Subnets (10.0.1.0/24 [AZ-A] · 10.0.2.0/24 [AZ-B])
│   ├── Internet Gateway (IGW) 연결 (아웃바운드 인터넷 직접 통신)
│   ├── Application Load Balancer (ALB) 배치
│   └── ECS Fargate 컨테이너 배치 (ALB 인바운드 허용, NAT 없이 외부 reCAPTCHA/Resend와 직접 통신)
│
└── Isolated Private Subnets (10.0.3.0/24 [AZ-A] · 10.0.4.0/24 [AZ-B])
    ├── 인터넷 라우팅 없음 (인터넷 게이트웨이 및 NAT 게이트웨이와 연결되지 않은 완전 고립)
    ├── RDS PostgreSQL 배치 (db.t4g.small, AZ-A 주 노드 & AZ-B 대기 노드 다중 영역 배치)
    └── ElastiCache Redis 배치 (cache.t4g.micro, AZ-A 기본 노드 & AZ-B 복제본 노드 복제)
```

### 2.1. 비용 최적화 및 보안 무결성 분석
- **NAT Gateway 배제 ($0/월)**:
  - Fargate 컴퓨트 노드를 퍼블릭 서브넷에 배치하여 인터넷 게이트웨이(IGW)를 통해 직접 Google reCAPTCHA 및 Resend API와 아웃바운드 통신을 전송하므로 NAT Gateway 고정 비용을 완전히 제거합니다.
- **스토리지 계층 격리**:
  - RDS 및 ElastiCache는 퍼블릭 IP가 없는 완전 고립 사설 서브넷(Isolated Private Subnet)에 배치하여 직접적인 인터넷 진입로를 원천 봉쇄합니다.
  - 보안 그룹 규칙(`RDS-SG`, `Redis-SG`)을 통해 오직 퍼블릭 서브넷 내 ECS Fargate 태스크의 사설 IP 대역만 진입할 수 있도록 엄격히 제한하여 안전성을 확보합니다.

---

## 3. 모니터링 및 로깅 구성 (Observability)

- **로그 그룹**: Amazon CloudWatch Logs `/aws/ecs/docsuri-api-service`
  - **보존 기간**: `30일` (비용 및 성능 분석 적합 범위)
  - **로깅 정책 (SEC-3)**: 애플리케이션 프레임워크 수준에서 필터링된 비민감 정보 로그만 전송합니다.
- **경보 설정 (CloudWatch Alarms)**:
  - **CPU 경보**: Fargate CPU 사용률 > 80% 상태가 5분 이상 지속 시 슬랙 및 OP 이메일 전송.
  - **Memory 경보**: Fargate Memory 사용률 > 80% 상태가 5분 이상 지속 시 경보.
  - **이메일 발송 실패 경보**: U3 도메인 신호 `EmailDeliveryFailureSignal` 발생 누적 횟수가 5분간 5회를 초과할 경우 임시 장애 상태로 판정하여 알림 발송.

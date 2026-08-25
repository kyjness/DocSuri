variable "project_name" {
  type        = string
  default     = "docsuri-demo"
  description = "리소스 이름 접두·비용 할당 태그에 공통 사용"
}

variable "region" {
  type    = string
  default = "ap-northeast-2"
}

variable "domain_name" {
  type        = string
  default     = "docsuri.shop"
  description = <<-EOT
    Caddy가 이 이름으로 Let's Encrypt 인증서를 받는다. **A 레코드는 Terraform이 만들지
    않는다** — 도메인을 가비아에서 샀고 네임서버가 그쪽에 있으므로, 고정 IP를 출력으로 받아
    가비아 DNS에 손으로 넣는다(`ops/deploy/README.md`).

    Route 53으로 위임하지 않는 이유: 호스팅 영역이 월 $0.50이고 데모 배포에서 그 값을 하는
    일이 A 레코드 하나뿐이다. 위임하면 되돌릴 때 전파를 또 기다린다.
  EOT
}

variable "lightsail_bundle_id" {
  type        = string
  default     = "large_3_0"
  description = <<-EOT
    **8 GB · 2 vCPU · SSD 160 GB**, $44/월 — 3개월 $144.

    4 GB(`medium_3_0`, $72)로 시작하려다 기각했다. 근거는 코퍼스·배포 질문지 Q1이고, 946편을
    실제로 색인해 잰 **편당 1.73 MB**가 그 근거다 — 4 GB의 실제 천장은 약 1,750편이라 기반
    논문 1,500편만으로 차고 최근분 자리가 없다. 8 GB의 천장이 약 3,500편이고 현재 색인이
    3,248편(93%)이다. **여유가 있어서 8 GB가 아니라 4 GB로는 성립하지 않아서**다.

    무료 번들(계정당 1개, 최대 2 GB)은 puppytalk이 쓴다 — DocSuri는 OpenSearch 때문에 2 GB로
    동작하지 않으므로 크레딧으로 지불한다.
  EOT
}

variable "lightsail_blueprint_id" {
  type        = string
  default     = "amazon_linux_2023"
  description = "OS 이미지. 기본 로그인 사용자는 ec2-user"
}

variable "lightsail_availability_zone" {
  type    = string
  default = "ap-northeast-2a"
}

variable "ssh_public_key" {
  type        = string
  description = <<-EOT
    배포용 공개키 본문. 개인키는 로컬에만 둔다 — `deploy.sh`가 이 키로 rsync·ssh 한다.
    puppytalk 배포키를 재사용하지 않는다: 한 키가 새면 두 서비스가 함께 열린다.
  EOT
}

variable "ssh_allowed_cidrs" {
  type        = list(string)
  default     = ["0.0.0.0/0"]
  description = <<-EOT
    22번 포트를 열어 줄 대역. 배포가 **사람의 노트북에서** 나가므로(수동 스크립트, CD 아님)
    고정 IP가 없어 기본은 전체 공개다. 인증은 키 전용이고 AL2023은 비밀번호 로그인이 기본
    비활성이다. 집·사무실 IP가 고정이라면 여기를 좁히는 것이 가장 값싼 강화다.
  EOT
}

variable "docker_compose_version" {
  type        = string
  default     = "v2.32.4"
  description = "user_data가 설치하는 compose 플러그인 버전(고정 = 재현 가능한 부트스트랩)"
}

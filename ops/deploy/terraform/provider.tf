terraform {
  required_version = ">= 1.3.2"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.40.0, < 6.0.0"
    }
  }

  # 원격 상태를 두지 않는다(로컬 tfstate). 혼자 쓰는 데모 배포 root이고 시크릿을 담지
  # 않으므로 S3+DynamoDB 잠금까지 갈 이유가 없다. `ops/cdk/`(실서비스 토폴로지 설계 기록)와
  # 이 디렉터리는 **서로 대체하지 않는다** — 설계 v3 §12.5가 그렇게 정했다.
}

locals {
  common_tags = {
    # 비용 할당 태그. Billing 콘솔에서 이 키를 활성화해야 프로젝트별 비용이 갈리고,
    # 활성화 후 24시간이 지나야 집계가 시작된다. puppytalk과 계정을 공유하므로 이게 없으면
    # 어느 쪽이 크레딧을 쓰는지 구분되지 않는다.
    Project     = var.project_name
    Environment = "demo"
    ManagedBy   = "terraform"
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.common_tags
  }
}

# 한 대에 전부 올라간다 — Caddy(TLS 종단) · 프론트(Next standalone) · 백엔드(uvicorn) ·
# postgres · redis · **opensearch**가 docker compose로 함께 뜬다(`../compose.prod.yml`).
#
# EC2가 아니라 Lightsail인 이유: 고정 IP·디스크·전송이 요금에 포함돼 월 비용이 절반이고,
# 데모 배포에 VPC·보안그룹·NAT를 직접 다룰 이유가 없다. 대가는 IAM 인스턴스 롤이 없어
# SSM 무키 배포를 못 쓰는 것(→ SSH 배포)과, S3 접근을 **액세스 키**로 해야 하는 것이다.
#
# **파싱 스택(GROBID 1.84 GB · Docling)은 여기 올리지 않는다**(질문지 Q7=B). 파싱·색인은
# 로컬에서 하고 배포에는 색인 결과만 올린다. 이 결정이 없으면 8 GB로도 성립하지 않고,
# 색인이 이미 천장의 93%라 자랄 자리도 없다.

resource "aws_lightsail_key_pair" "deploy" {
  name       = "${var.project_name}-deploy"
  public_key = var.ssh_public_key
}

resource "aws_lightsail_instance" "app" {
  name              = "${var.project_name}-app"
  availability_zone = var.lightsail_availability_zone
  blueprint_id      = var.lightsail_blueprint_id
  bundle_id         = var.lightsail_bundle_id
  key_pair_name     = aws_lightsail_key_pair.deploy.name

  # 여기서는 "컨테이너를 돌릴 수 있는 상태"까지만 만든다. compose 파일과 `.env.prod`(시크릿)는
  # `deploy.sh`가 올린다 — user_data에 시크릿을 넣으면 인스턴스 메타데이터에 평문으로 남는다.
  user_data = <<-EOT
    #!/bin/bash
    set -euxo pipefail

    dnf install -y docker rsync
    systemctl enable --now docker
    usermod -aG docker ec2-user

    mkdir -p /usr/libexec/docker/cli-plugins
    curl -sSL "https://github.com/docker/compose/releases/download/${var.docker_compose_version}/docker-compose-linux-x86_64" \
      -o /usr/libexec/docker/cli-plugins/docker-compose
    chmod +x /usr/libexec/docker/cli-plugins/docker-compose

    # OpenSearch가 요구하는 커널 설정. **없으면 부팅에 실패한다** — 컨테이너가 뜨자마자
    # `max virtual memory areas vm.max_map_count [65530] is too low`로 죽고, 그 실패는
    # compose 로그를 열기 전까지 "검색이 안 된다"로만 보인다.
    echo 'vm.max_map_count=262144' > /etc/sysctl.d/99-opensearch.conf
    sysctl -p /etc/sysctl.d/99-opensearch.conf

    # 색인 구축이 아니라 **적재**만 하는 박스이지만, 색인 복원과 첫 기동이 순간적으로 힘을
    # 준다. OOM 킬러가 postgres를 먼저 죽이는 것을 막는 완충재.
    if [ ! -f /swapfile ]; then
      dd if=/dev/zero of=/swapfile bs=1M count=4096
      chmod 600 /swapfile
      mkswap /swapfile
      swapon /swapfile
      echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi

    mkdir -p /opt/docsuri
    chown ec2-user:ec2-user /opt/docsuri
  EOT
}

resource "aws_lightsail_static_ip" "app" {
  name = "${var.project_name}-ip"
}

resource "aws_lightsail_static_ip_attachment" "app" {
  static_ip_name = aws_lightsail_static_ip.app.name
  instance_name  = aws_lightsail_instance.app.name
}

# 이 블록이 인스턴스의 방화벽 규칙 **전체**를 대체한다 — 여기 없는 규칙은 닫힌다.
# 그래서 9200(OpenSearch)·5432(postgres)·8000(백엔드)이 명시적으로 빠져 있다: 전부 compose
# 내부 네트워크로만 닿고 밖으로 안 낸다. OpenSearch는 보안 플러그인을 끈 채로 도므로
# **한 줄만 잘못 열려도 인증 없이 코퍼스 전체가 읽힌다.**
resource "aws_lightsail_instance_public_ports" "app" {
  instance_name = aws_lightsail_instance.app.name

  port_info {
    protocol  = "tcp"
    from_port = 80 # ACME HTTP-01 챌린지 + HTTPS 리다이렉트
    to_port   = 80
    cidrs     = ["0.0.0.0/0"]
  }

  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
    cidrs     = ["0.0.0.0/0"]
  }

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = var.ssh_allowed_cidrs
  }
}

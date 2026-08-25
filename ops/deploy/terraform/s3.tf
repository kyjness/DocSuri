# 로컬은 s3proxy가 `~/data/docsuri-deploy/s3`를 버킷처럼 서빙한다. 배포는 **실 S3**다
# (설계 §12.2) — 박스 디스크에 24 GB 자산을 얹으면 색인 몫을 먹는다.
#
# Lightsail에는 인스턴스 롤이 없다. 그래서 앱 전용 IAM 사용자를 만들고 **그 키를
# `.env.prod`로** 넘긴다. 키는 Terraform 출력에 민감값으로 남으므로 tfstate를 커밋하지 않는다
# (`.gitignore` 참조).

resource "aws_s3_bucket" "assets" {
  bucket = "${var.project_name}-assets"
}

# 공개 접근을 네 갈래 전부 막는다. 이 버킷에는 논문 전문·그림 crop이 들어가고, 프론트는
# 그것을 **백엔드를 거쳐** 받는다(직접 S3를 치지 않는다). 한 갈래라도 열어 두면 버킷 이름만
# 알면 코퍼스가 통째로 긁힌다.
resource "aws_s3_bucket_public_access_block" "assets" {
  bucket                  = aws_s3_bucket.assets.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_iam_user" "app" {
  name = "${var.project_name}-app"
}

# 버킷 하나로 좁힌다. `s3:*`도 계정 전체도 아니다 — puppytalk과 계정을 공유하므로 넓은
# 정책 하나가 남의 버킷까지 연다.
resource "aws_iam_user_policy" "app_s3" {
  name = "${var.project_name}-app-s3"
  user = aws_iam_user.app.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.assets.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.assets.arn
      },
    ]
  })
}

# Bedrock — 요약·번역·evidence·novelty가 전부 여기를 친다. 모델 호출만 허용하고
# 모델 관리·프로비저닝은 안 준다.
resource "aws_iam_user_policy" "app_bedrock" {
  name = "${var.project_name}-app-bedrock"
  user = aws_iam_user.app.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Rerank"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_access_key" "app" {
  user = aws_iam_user.app.name
}

output "static_ip" {
  value       = aws_lightsail_static_ip.app.ip_address
  description = "가비아 DNS에 A 레코드로 넣는 값 — `docsuri.shop`과 `www` 둘 다"
}

output "ssh" {
  value       = "ssh -i <개인키> ec2-user@${aws_lightsail_static_ip.app.ip_address}"
  description = "배포·점검용 접속 명령"
}

output "s3_bucket" {
  value       = aws_s3_bucket.assets.bucket
  description = "DOCSURI_S3_BUCKET · DOCSURI_DOCMODEL_BUCKET에 넣는 값"
}

output "app_access_key_id" {
  value       = aws_iam_access_key.app.id
  description = "AWS_ACCESS_KEY_ID — `.env.prod`로 넘긴다"
}

output "app_secret_access_key" {
  value       = aws_iam_access_key.app.secret
  sensitive   = true
  description = "AWS_SECRET_ACCESS_KEY — `terraform output -raw app_secret_access_key`로 꺼낸다"
}

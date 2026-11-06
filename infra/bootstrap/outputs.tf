output "state_bucket_name" {
  value = aws_s3_bucket.bootstrap.bucket
}

output "github_actions_role_arn" {
  description = "Set this as the AWS_ROLE_ARN variable in the GitHub repository settings."
  value       = aws_iam_role.github_actions.arn
}

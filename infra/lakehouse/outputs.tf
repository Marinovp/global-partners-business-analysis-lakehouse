output "account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "name_prefix" {
  value = local.name_prefix
}

output "bucket_name" {
  value = aws_s3_bucket.lakehouse.bucket
}

output "seed_job_name" {
  value = aws_glue_job.seed.name
}

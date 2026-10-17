output "account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "name_prefix" {
  value = local.name_prefix
}

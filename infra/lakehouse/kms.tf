resource "aws_kms_key" "lakehouse" {
  description             = "Encrypts lakehouse ${var.environment} data (S3, logs)"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Name = "${local.name_prefix}-kms"
  }
}

resource "aws_kms_alias" "lakehouse" {
  name          = "alias/${local.name_prefix}"
  target_key_id = aws_kms_key.lakehouse.key_id
}

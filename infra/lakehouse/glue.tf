locals {
  source_db_name  = "globalpartners"
  seed_script_src = "${path.module}/../../etl/jobs/seed_rds.py"
}

# How Glue jobs get into the VPC: Glue places the job's network interfaces in this
# subnet with this security group, then reads DB credentials from the RDS-managed secret.
resource "aws_glue_connection" "sqlserver" {
  name            = "${local.name_prefix}-sqlserver"
  connection_type = "JDBC"

  connection_properties = {
    # RDS SQL Server starts with system databases only; the seed job creates this one.
    JDBC_CONNECTION_URL = "jdbc:sqlserver://${aws_db_instance.source.address}:${aws_db_instance.source.port};databaseName=${local.source_db_name}"
    SECRET_ID           = aws_db_instance.source.master_user_secret[0].secret_arn
  }

  physical_connection_requirements {
    availability_zone      = aws_subnet.private[0].availability_zone
    subnet_id              = aws_subnet.private[0].id
    security_group_id_list = [aws_security_group.glue.id]
  }

  tags = {
    Name = "${local.name_prefix}-sqlserver"
  }
}

# Upload the job script on every apply. source_hash (not etag) because the bucket encrypts
# with KMS, and the S3 ETag of a KMS-encrypted object is not the file's MD5.
resource "aws_s3_object" "seed_script" {
  bucket      = aws_s3_bucket.lakehouse.id
  key         = "artifacts/jobs/seed_rds.py"
  source      = local.seed_script_src
  source_hash = filemd5(local.seed_script_src)
}

# Loads seed/*.csv into RDS: the simulated source system the pipeline extracts from.
resource "aws_glue_job" "seed" {
  name              = "${local.name_prefix}-seed-rds"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 30
  max_retries       = 0
  connections       = [aws_glue_connection.sqlserver.name]

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.lakehouse.bucket}/${aws_s3_object.seed_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--TempDir"                          = "s3://${aws_s3_bucket.lakehouse.bucket}/artifacts/tmp/"
    "--enable-continuous-cloudwatch-log" = "true"
    "--bucket"                           = aws_s3_bucket.lakehouse.bucket
    "--db_host"                          = aws_db_instance.source.address
    "--db_port"                          = tostring(aws_db_instance.source.port)
    "--db_name"                          = local.source_db_name
    "--secret_arn"                       = aws_db_instance.source.master_user_secret[0].secret_arn
    "--aws_region"                       = var.aws_region
  }

  tags = {
    Name = "${local.name_prefix}-seed-rds"
  }
}

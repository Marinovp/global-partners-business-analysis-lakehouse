# RDS needs a subnet group spanning at least 2 AZs, even for a single-AZ instance.
resource "aws_db_subnet_group" "lakehouse" {
  name       = "${local.name_prefix}-db-subnets"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.name_prefix}-db-subnets"
  }
}

# Reject any client connection that doesn't use TLS.
resource "aws_db_parameter_group" "lakehouse" {
  name   = "${local.name_prefix}-sqlserver"
  family = "sqlserver-ex-16.0"

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }

  tags = {
    Name = "${local.name_prefix}-sqlserver"
  }
}

resource "aws_db_instance" "source" {
  identifier        = "${local.name_prefix}-sqlserver"
  engine            = "sqlserver-ex"
  engine_version    = "16.00"
  license_model     = "license-included"
  instance_class    = "db.t3.micro"
  allocated_storage = 20

  # RDS generates the password and stores it in Secrets Manager; it never appears in code or state.
  username                    = "dbadmin"
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.lakehouse.name
  parameter_group_name   = aws_db_parameter_group.lakehouse.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  storage_encrypted = true
  kms_key_id        = aws_kms_key.lakehouse.arn

  # Dev stack is destroyed daily: no final snapshot, no automated backups.
  skip_final_snapshot     = true
  backup_retention_period = 0
  apply_immediately       = true

  tags = {
    Name = "${local.name_prefix}-sqlserver"
  }
}

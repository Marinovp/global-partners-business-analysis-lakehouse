resource "aws_glue_catalog_database" "raw" {
  name = "gp_raw"
}

resource "aws_glue_catalog_database" "silver" {
  name = "gp_silver"
}

resource "aws_glue_catalog_database" "gold" {
  name = "gp_gold"
}

resource "aws_athena_workgroup" "lakehouse" {
  name = "${local.name_prefix}-wg"

  configuration {
    bytes_scanned_cutoff_per_query = 1073741824 # 1 GB: queries over this are cancelled

    result_configuration {
      output_location = "s3://${aws_s3_bucket.lakehouse.bucket}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.lakehouse.arn
      }
    }
  }
}

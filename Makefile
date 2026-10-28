.PHONY: init plan apply destroy seed seed-rds extract silver check pipeline
TF_DIR := infra/lakehouse

ifndef ENV
$(error ENV is not set, e.g make ENV=dev)
endif

init:
	@echo "Initializing Terraform..."
	terraform -chdir=$(TF_DIR) init -reconfigure -backend-config=env/$(ENV).backend.hcl

plan: init
	@echo "Planning Terraform changes..."
	terraform -chdir=$(TF_DIR) plan -var-file=env/$(ENV).tfvars -out=tfplan

apply:
	@echo "Applying Terraform changes..."
	terraform -chdir=$(TF_DIR) apply tfplan

destroy: init
	@echo "Destroying Terraform changes..."
	terraform -chdir=$(TF_DIR) destroy -var-file=env/$(ENV).tfvars -auto-approve

seed: init
	aws s3 sync data/ s3://$$(terraform -chdir=$(TF_DIR) output -raw bucket_name)/seed/

# Start the Glue job that loads seed/*.csv into RDS (prints the job run ID).
seed-rds: init
	aws glue start-job-run --job-name $$(terraform -chdir=$(TF_DIR) output -raw seed_job_name) --query JobRunId --output text

# Start job 0 (extract): SQL Server → S3 raw/ (prints the job run ID).
extract: init
	aws glue start-job-run --job-name $$(terraform -chdir=$(TF_DIR) output -raw extract_job_name) --query JobRunId --output text

# Start job 1 (silver): raw → Iceberg tables in gp_silver.
silver: init
	aws glue start-job-run --job-name $$(terraform -chdir=$(TF_DIR) output -raw silver_job_name) --query JobRunId --output text

# Run the whole pipeline (extract → silver, in order) as one Glue Workflow run; prints the run ID.
pipeline: init
	aws glue start-workflow-run --name $$(terraform -chdir=$(TF_DIR) output -raw workflow_name) --query RunId --output text

# Catch typos before review: Terraform formatting + validation, and Python syntax of every job script.
check:
	terraform -chdir=$(TF_DIR) fmt -check -diff
	terraform -chdir=$(TF_DIR) validate
	python3 -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]; print('python syntax OK:', *sys.argv[1:])" etl/jobs/*.py

.PHONY: init plan apply destroy
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

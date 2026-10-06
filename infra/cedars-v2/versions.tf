terraform {
  required_version = ">= 1.6"

  # Terraform Cloud. State lives in TFC; AWS auth is via the workspace's
  # dynamic OIDC credentials — no static keys / AWS_PROFILE. The organization
  # and workspace come from TF_CLOUD_ORGANIZATION and TF_WORKSPACE at init, so
  # they stay out of this repo.
  cloud {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.21"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

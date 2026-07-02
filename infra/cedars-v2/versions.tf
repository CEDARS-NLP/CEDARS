terraform {
  required_version = ">= 1.6"

  # Terraform Cloud (MSK org standard). State lives in TFC; AWS auth is via
  # the workspace's dynamic OIDC credentials — no static keys / AWS_PROFILE.
  # The workspace name can be overridden at init with TF_WORKSPACE.
  cloud {
    organization = "mskcc"

    workspaces {
      name = "APM0004784-aws-research-us-east-1-ctdatahubpoc"
    }
  }

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

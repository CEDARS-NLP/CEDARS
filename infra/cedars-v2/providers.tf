provider "aws" {
  region = var.region

  # Guard against applying to the wrong account. Set var.allowed_account_ids
  # as a workspace variable; there is deliberately no default.
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = {
      Project     = "cedars-v2"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "cedars"
    }
  }
}

'''
Seed the system principals referenced by automatic review records.
'''
from alembic import op


revision = "0002_seed_system_reviewers"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        '''
        INSERT INTO "ProjectUsers" ("user_id", "is_admin")
        VALUES ('CEDARS', FALSE), ('PINES', FALSE)
        ON CONFLICT ("user_id") DO NOTHING
        '''
    )


def downgrade() -> None:
    pass
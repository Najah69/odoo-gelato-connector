# Copyright 2024 Contributors
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
# Removes the unique SQL constraint on company_id that was created in v1.0.0.
# It prevented creating a new config after archiving the previous one for the
# same company. Replaced by a Python @api.constrains that only checks active records.


def migrate(cr, version):
    cr.execute("ALTER TABLE gelato_config " "DROP CONSTRAINT IF EXISTS gelato_config_company_uniq")

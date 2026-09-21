-- Read-only safety check before moving the existing Volume registrations.
-- This is deliberately a small verification, not a full platform inventory.

DESCRIBE VOLUME `finops_dev`.`raw`.`focus`;
DESCRIBE VOLUME `finops_dev`.`raw`.`focus_archive`;

LIST '/Volumes/finops_dev/raw/focus/monthly';


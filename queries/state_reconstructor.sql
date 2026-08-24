-- Point-in-time legal state reconstruction
-- Temporal Legal Intelligence Platform (sandbox)
--
-- Core pattern: interval overlap on effective_from / effective_to
--   effective_from <= :target_date AND (effective_to >= :target_date OR effective_to IS NULL)
--
-- Maps to production ORM queries in packages/legal_core_client/client.py

-- ---------------------------------------------------------------------------
-- 1. Provision text as-of a date (base corpus version)
-- ---------------------------------------------------------------------------
-- Returns the provision_version row that was legally operative on :target_date.
-- Prefer highest version_number when multiple rows overlap (amendment chain).

SELECT
    pv.id                   AS version_id,
    pv.version_number,
    pv.text_content,
    pv.effective_from,
    pv.effective_to,
    pv.as_on_date,
    p.provision_code,
    p.provision_type,
    p.label
FROM provision_versions pv
JOIN provisions p ON p.id = pv.provision_id
WHERE p.provision_code = :provision_code          -- e.g. 'CGST-S16'
  AND (pv.effective_from IS NULL OR pv.effective_from <= :target_date)
  AND (pv.effective_to   IS NULL OR pv.effective_to   >= :target_date)
ORDER BY pv.version_number DESC
LIMIT 1;


-- ---------------------------------------------------------------------------
-- 2. Effectivity status as-of a date (in force / repealed / not commenced)
-- ---------------------------------------------------------------------------

SELECT
    le.status,
    le.jurisdiction_id,
    le.effective_from,
    le.effective_to,
    le.notes
FROM legal_effectivity le
JOIN provisions p ON p.id = le.provision_id
WHERE p.provision_code = :provision_code
  AND (:jurisdiction_id IS NULL OR le.jurisdiction_id = :jurisdiction_id)
  AND (le.effective_from IS NULL OR le.effective_from <= :target_date)
  AND (le.effective_to   IS NULL OR le.effective_to   >= :target_date);


-- ---------------------------------------------------------------------------
-- 3. Amendment chain affecting a provision (notifications → sub-rule inserts)
-- ---------------------------------------------------------------------------
-- Application order: effective_from ASC; last amendment per sub_provision_label wins.
-- Text composition (INSERT/SUBSTITUTE into base text) is done in application layer
-- (services/legal_text/composer.py in the full platform).

SELECT
    rn.notification_code,
    rn.notification_number,
    rn.issued_date,
    pa.change_type,
    pa.sub_provision_label,
    pa.effective_from,
    pa.inserted_text,
    pa.notes
FROM provision_amendments pa
JOIN regulatory_notifications rn ON rn.id = pa.notification_id
JOIN provisions p ON p.id = pa.provision_id
WHERE p.provision_code = :provision_code
  AND (pa.effective_from IS NULL OR pa.effective_from <= :target_date)
ORDER BY
    pa.effective_from ASC NULLS FIRST,
    rn.issued_date ASC NULLS FIRST;


-- ---------------------------------------------------------------------------
-- 4. Graph neighbourhood — rules implementing sections (metadata relationships)
-- ---------------------------------------------------------------------------

SELECT
    p_from.provision_code  AS from_code,
    pr.relationship_type,
    p_to.provision_code    AS to_code
FROM provision_relationships pr
JOIN provisions p_from ON p_from.id = pr.from_provision_id
JOIN provisions p_to   ON p_to.id   = pr.to_provision_id
WHERE p_from.provision_code = :provision_code
   OR p_to.provision_code   = :provision_code;


-- ---------------------------------------------------------------------------
-- 5. Matter timeline — all provisions in force for an instrument on a date
-- ---------------------------------------------------------------------------
-- Optimized for index: (provision_id, effective_from, effective_to)

SELECT
    p.provision_code,
    p.label,
    pv.text_content,
    le.status
FROM provisions p
JOIN legal_instruments li ON li.id = p.instrument_id
LEFT JOIN LATERAL (
    SELECT pv2.*
    FROM provision_versions pv2
    WHERE pv2.provision_id = p.id
      AND (pv2.effective_from IS NULL OR pv2.effective_from <= :target_date)
      AND (pv2.effective_to   IS NULL OR pv2.effective_to   >= :target_date)
    ORDER BY pv2.version_number DESC
    LIMIT 1
) pv ON TRUE
LEFT JOIN LATERAL (
    SELECT le2.status
    FROM legal_effectivity le2
    WHERE le2.provision_id = p.id
      AND (le2.effective_from IS NULL OR le2.effective_from <= :target_date)
      AND (le2.effective_to   IS NULL OR le2.effective_to   >= :target_date)
    LIMIT 1
) le ON TRUE
WHERE li.instrument_code = :instrument_code   -- e.g. 'CGST-2017'
  AND le.status = 'IN_FORCE'
ORDER BY
    CASE WHEN p.label ~ '^\d+$' THEN p.label::int END NULLS LAST,
    p.label;

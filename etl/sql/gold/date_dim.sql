-- Mirrors date_dim() + us_federal_holidays() in etl/jobs/gold.py → gp_gold.date_dim.
-- One row per calendar day for every full year the data touches (2020-2024).
-- Holidays: US federal holidays on their calendar dates (observed-day shifts not applied).
-- The company's own holiday list wasn't available; this is an assumption to confirm.
-- day_of_week(): Monday = 1 ... Sunday = 7.

WITH years AS (
  SELECT y FROM UNNEST(sequence(2020, 2024)) AS t(y)
),
month_starts AS (  -- first day of the months that have "nth weekday" holidays
  SELECT y,
         date(format('%d-01-01', y)) AS jan, date(format('%d-02-01', y)) AS feb,
         date(format('%d-05-31', y)) AS may31, date(format('%d-09-01', y)) AS sep,
         date(format('%d-10-01', y)) AS oct, date(format('%d-11-01', y)) AS nov
  FROM years
),
holidays AS (
  SELECT date(format('%d-01-01', y)) AS date_key, 'New Year''s Day' AS holiday_name FROM years
  UNION ALL SELECT date_add('day', (8 - day_of_week(jan)) % 7 + 14, jan), 'Martin Luther King Jr. Day' FROM month_starts  -- 3rd Monday
  UNION ALL SELECT date_add('day', (8 - day_of_week(feb)) % 7 + 14, feb), 'Presidents'' Day' FROM month_starts          -- 3rd Monday
  UNION ALL SELECT date_add('day', -((day_of_week(may31) + 6) % 7), may31), 'Memorial Day' FROM month_starts           -- last Monday
  UNION ALL SELECT date(format('%d-06-19', y)), 'Juneteenth' FROM years WHERE y >= 2021
  UNION ALL SELECT date(format('%d-07-04', y)), 'Independence Day' FROM years
  UNION ALL SELECT date_add('day', (8 - day_of_week(sep)) % 7, sep), 'Labor Day' FROM month_starts                     -- 1st Monday
  UNION ALL SELECT date_add('day', (8 - day_of_week(oct)) % 7 + 7, oct), 'Columbus Day' FROM month_starts              -- 2nd Monday
  UNION ALL SELECT date(format('%d-11-11', y)), 'Veterans Day' FROM years
  UNION ALL SELECT date_add('day', (11 - day_of_week(nov)) % 7 + 21, nov), 'Thanksgiving Day' FROM month_starts        -- 4th Thursday
  UNION ALL SELECT date(format('%d-12-25', y)), 'Christmas Day' FROM years
),
days AS (
  SELECT CAST(d AS date) AS date_key
  FROM UNNEST(sequence(DATE '2020-01-01', DATE '2024-12-31', INTERVAL '1' DAY)) AS t(d)
)
SELECT d.date_key,
       format_datetime(d.date_key, 'EEEE')   AS day_of_week,
       week(d.date_key)                      AS week,
       format_datetime(d.date_key, 'MMMM')   AS month,
       month(d.date_key)                     AS month_number,
       quarter(d.date_key)                   AS quarter,
       year(d.date_key)                      AS year,
       day_of_week(d.date_key) IN (6, 7)     AS is_weekend,
       h.holiday_name IS NOT NULL            AS is_holiday,
       h.holiday_name
FROM days d
LEFT JOIN holidays h ON d.date_key = h.date_key;

-- ============================================================================
-- Add strategy_group to products table
-- Run this SQL in Supabase SQL Editor
-- Source: Data ICPL product for iDA - สำหรับ view.csv
-- ============================================================================

-- 1. Add strategy_group column
ALTER TABLE products ADD COLUMN IF NOT EXISTS strategy_group TEXT;

-- 2. Update strategy_group for each product (use TRIM for safety)
-- Expand group
UPDATE products SET strategy_group = 'Expand' WHERE TRIM(product_name) = 'โมเดิน 50';
UPDATE products SET strategy_group = 'Expand' WHERE TRIM(product_name) = 'พรีดิคท์ 25';
UPDATE products SET strategy_group = 'Expand' WHERE TRIM(product_name) = 'ราเซอร์';
UPDATE products SET strategy_group = 'Expand' WHERE TRIM(product_name) = 'โค-ราซ';
UPDATE products SET strategy_group = 'Expand' WHERE TRIM(product_name) = 'นาแดน-จี';
UPDATE products SET strategy_group = 'Expand' WHERE TRIM(product_name) = 'นาแดน 6 จี';
UPDATE products SET strategy_group = 'Expand' WHERE TRIM(product_name) = 'เลกาซี 20 + พานาส';
UPDATE products SET strategy_group = 'Expand' WHERE TRIM(product_name) = 'พรีดิคท์ 15';
UPDATE products SET strategy_group = 'Expand' WHERE TRIM(product_name) = 'พรีดิคท์ 10%';

-- Natural group
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'พาสนาว';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'ก๊อปกัน';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'แอนดาแม็กซ์';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'อัพดาว';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'กะรัต 35';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'เบนซาน่า เอฟ';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'ไดแพ๊กซ์ 80 ดับเบิ้ลยู.จี.';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'อิมิดาโกลด์ 70';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'เกรค 5 เอสซี';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'โคเบิล';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'โคเบิ้ล';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'แจ๊ส 50 อีซี';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'ซีเอ็มจี';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'ซิมเมอร์';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'โซนิก';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'เคเซีย';
UPDATE products SET strategy_group = 'Natural' WHERE TRIM(product_name) = 'บลูไวท์';

-- Skyrocket group
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'ทูโฟฟอส';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'อะนิลการ์ด';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'ไฮซีส';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) LIKE 'ชุด กล่องม่วง%';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'แกนเตอร์';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'โฮป';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'คาริสมา';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'อาร์เทมีส';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'ไซม๊อกซิเมท';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'แอสไปร์';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'เมลสัน';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'อาร์ดอน';
UPDATE products SET strategy_group = 'Skyrocket' WHERE TRIM(product_name) = 'โม-เซ่ 88.8';

-- Standard group
UPDATE products SET strategy_group = 'Standard' WHERE TRIM(product_name) = 'วอร์แรนต์';
UPDATE products SET strategy_group = 'Standard' WHERE TRIM(product_name) = 'เทอราโน่';
UPDATE products SET strategy_group = 'Standard' WHERE TRIM(product_name) = 'รีโนเวท';
UPDATE products SET strategy_group = 'Standard' WHERE TRIM(product_name) = 'ไฮจิพ 20';
UPDATE products SET strategy_group = 'Standard' WHERE TRIM(product_name) = 'แมสฟอร์ด';
UPDATE products SET strategy_group = 'Standard' WHERE TRIM(product_name) = 'ไพรซีน';

-- 3. Verify: show products and their strategy_group
SELECT product_name, strategy_group, category
FROM products
ORDER BY strategy_group, product_name;

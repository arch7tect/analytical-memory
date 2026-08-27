ALTER TABLE node_attribute ADD COLUMN sort_text_folded TEXT;
ALTER TABLE node_attribute ADD COLUMN sort_text_exact TEXT;
ALTER TABLE node_attribute ADD COLUMN sort_number REAL;

CREATE INDEX node_attribute_text_sort_idx
    ON node_attribute(json_type, sort_text_folded, sort_text_exact);

CREATE INDEX node_attribute_number_sort_idx
    ON node_attribute(json_type, sort_number);

PRAGMA user_version = 6;

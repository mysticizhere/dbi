/**
 * Columns offered to the SQL editor for completion.
 *
 * Hand-maintained to match backend/seed/seed.py. Reading it from the server at
 * startup would be more correct, but this is one table in a lab whose schema is
 * part of the teaching material -- it changes when the exercises change.
 */
export const LAB_SCHEMA: Record<string, string[]> = {
  events: [
    "id",
    "user_id",
    "score",
    "status",
    "city",
    "pincode",
    "email",
    "sku",
    "payload",
    "created_at",
  ],
};

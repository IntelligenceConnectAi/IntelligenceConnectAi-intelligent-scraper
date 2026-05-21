import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error(
    "Missing Supabase env vars. Check frontend/.env — VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY are required."
  );
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: true,      // Save session to localStorage
    autoRefreshToken: true,    // Auto-refresh before expiry
    detectSessionInUrl: false, // No magic links yet
  },
});

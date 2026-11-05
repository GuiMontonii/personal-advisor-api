-- AssessorIA - schema e ajustes repetíveis (PostgreSQL)
-- Execute apenas após backup do banco. Não apaga tabelas nem registros.
-- Se alguma instrução falhar, a transação inteira é desfeita.
BEGIN;

CREATE TABLE IF NOT EXISTS categories (
  id           SERIAL PRIMARY KEY,
  name         VARCHAR(64) NOT NULL,             
  description  TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()                        
);

CREATE TABLE IF NOT EXISTS transaction_types (
  id      serial PRIMARY KEY,
  type    TEXT NOT NULL                                        
);

CREATE TABLE IF NOT EXISTS transactions (
  id             BIGSERIAL PRIMARY KEY,
  amount         NUMERIC(14,2) NOT NULL , 	
  type           INT REFERENCES transaction_types(id) NOT NULL DEFAULT 2,          
  category_id    INT REFERENCES categories(id) ON DELETE SET NULL,
  description    TEXT,                                                
  payment_method VARCHAR(32),                                         
  occurred_at    TIMESTAMPTZ NOT NULL,                                
  source_text    TEXT NOT NULL                                        
);

CREATE INDEX IF NOT EXISTS idx_transactions_occurred_at
  ON transactions (occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_category_time
  ON transactions (category_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_localday
  ON transactions ( ((occurred_at AT TIME ZONE 'America/Sao_Paulo')::date) );

CREATE TABLE IF NOT EXISTS events (
  id           BIGSERIAL PRIMARY KEY,
  title        TEXT NOT NULL,                                          
  start_time   TIMESTAMPTZ NOT NULL,                                   
  end_time     TIMESTAMPTZ,                                            
  location     TEXT,
  notes        TEXT,
  recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),                     
  source_text  TEXT NOT NULL                                           
);

-- Compatibilidade não destrutiva com a outra versão "Completo Corrigido":
-- se aquele SQL já renomeou events, recuperamos os nomes do schema original
-- sem apagar nem recriar a tabela, evitando incompatibilidade com app/tools/agenda.py.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = 'events' AND column_name = 'start_at')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = 'events' AND column_name = 'start_time') THEN
    ALTER TABLE events RENAME COLUMN start_at TO start_time;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = 'events' AND column_name = 'end_at')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = 'events' AND column_name = 'end_time') THEN
    ALTER TABLE events RENAME COLUMN end_at TO end_time;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = 'events' AND column_name = 'description')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = 'events' AND column_name = 'notes') THEN
    ALTER TABLE events RENAME COLUMN description TO notes;
  END IF;
END $$;

-- Caso o script alternativo já tenha criado events, reintroduz apenas as colunas
-- legadas necessárias; o conteúdo existente permanece intacto.
ALTER TABLE events ADD COLUMN IF NOT EXISTS end_time TIMESTAMPTZ;
ALTER TABLE events ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS location TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE events ADD COLUMN IF NOT EXISTS source_text TEXT;
UPDATE events SET source_text = title WHERE source_text IS NULL;
ALTER TABLE events ALTER COLUMN source_text SET NOT NULL;

-- Em bancos já existentes, acrescenta apenas o identificador do usuário.
-- Compromissos antigos são associados ao usuário padrão usado pelo projeto.
ALTER TABLE events ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'usuario_teste';
UPDATE events SET user_id = 'usuario_teste' WHERE user_id IS NULL;
ALTER TABLE events ALTER COLUMN user_id SET DEFAULT 'usuario_teste';
ALTER TABLE events ALTER COLUMN user_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_events_user_period
  ON events (user_id, start_time, end_time);

CREATE INDEX IF NOT EXISTS idx_events_start_time
  ON events (start_time DESC);

-- Evita duplicar dados ao executar novamente o arquivo.
INSERT INTO transaction_types (type)
SELECT s.type
FROM (VALUES ('INCOME'), ('EXPENSES'), ('TRANSFER')) AS s(type)
WHERE NOT EXISTS (
    SELECT 1 FROM transaction_types t WHERE UPPER(t.type) = s.type
);

INSERT INTO categories (name)
SELECT s.name
FROM (VALUES
  ('comida'),
  ('besteira'),
  ('estudo'),
  ('férias'),
  ('transporte'),
  ('moradia'),
  ('saúde'),
  ('lazer'),
  ('contas'),
  ('investimento'),
  ('presente'),
  ('outros')
) AS s(name)
WHERE NOT EXISTS (
    SELECT 1 FROM categories c WHERE LOWER(c.name) = LOWER(s.name)
);

-- Ajusta o default legado (2) para o ID real de EXPENSES, que pode variar.
DO $$
DECLARE id_despesa integer;
BEGIN
  SELECT id INTO id_despesa FROM transaction_types
  WHERE UPPER(type) = 'EXPENSES' ORDER BY id LIMIT 1;
  IF id_despesa IS NOT NULL THEN
    EXECUTE format('ALTER TABLE transactions ALTER COLUMN type SET DEFAULT %s', id_despesa);
  END IF;
END $$;

-- Horários locais são calculados explicitamente em America/Sao_Paulo pelo backend.

COMMIT;

# Supabase + InfluxDB para PCAP procesado (replanteamiento)

## Objetivo

Diseñar un pipeline estable para:

- captura de tráfico (AP),
- extracción de datos relevantes,
- búsqueda vectorial,
- entrenamiento de modelos,
- observabilidad temporal.

---

## Decisión técnica

- **PCAP crudo**: filesystem/S3 (no BD principal).
- **InfluxDB**: métricas agregadas por ventana de tiempo.
- **Supabase/Postgres**: eventos estructurados + embeddings + etiquetas.

Esto separa bien:

- analítica temporal rápida (Influx),
- forense/IA y búsquedas semánticas (Supabase).

---

## Estado actual (tu esquema)

Ya tienes `public.network_packets` (correcto como tabla base de eventos de red).

La vectorización debe vivir aparte en una tabla tipo `*_embeddings` (como ya haces con `tactics_embeddings`).

---

## Esquema recomendado para red (alineado a tu patrón actual)

```sql
create extension if not exists vector;

create table if not exists public.network_packet_embeddings (
	id uuid primary key default gen_random_uuid(),
	packet_id uuid not null,
	embedding vector(384),
	text_content text not null,
	metadata jsonb,
	created_at timestamptz default now(),
	constraint network_packet_embeddings_packet_id_key unique (packet_id),
	constraint network_packet_embeddings_packet_id_fkey
		foreign key (packet_id)
		references public.network_packets(id)
		on delete cascade
);

create index if not exists network_packet_embeddings_vector_idx
	on public.network_packet_embeddings
	using ivfflat (embedding vector_cosine_ops)
	with (lists = 100);

create index if not exists idx_network_packets_ts
	on public.network_packets (timestamp desc);
```

> Nota: si no quieres `text_content`, puedes mantener `embedding_model` + `content_hash`; pero tu patrón actual (`tactics_embeddings`) usa `text_content` y es consistente.

---

## Por qué te falló el query anterior

Error observado:

`ERROR: expected 384 dimensions, not 3`

Causa:

- el vector de prueba tenía 3 elementos (`[0.12, -0.03, 0.44]`),
- la columna está en 384 dimensiones (`vector(384)`).

En pgvector, la dimensión debe coincidir exactamente.

---

## SQL correcto para prueba rápida

### Opción A: usar un embedding real existente (recomendado)

```sql
with q as (
	select embedding as query_embedding
	from public.network_packet_embeddings
	where embedding is not null
	limit 1
)
select
	p.id,
	p.timestamp,
	p.src_ip,
	p.dst_ip,
	p.protocol,
	p.is_malicious,
	1 - (e.embedding <=> q.query_embedding) as similarity
from public.network_packet_embeddings e
join public.network_packets p on p.id = e.packet_id
cross join q
where p.timestamp >= now() - interval '7 days'
order by e.embedding <=> q.query_embedding
limit 20;
```

### Opción B: vector literal (solo si pegas 384 valores)

```sql
-- '[v1, v2, ..., v384]'::vector(384)
```

---

## RPC recomendada (estilo igual a tu `supabase_client.py`)

```sql
create or replace function public.search_similar_network_packets(
	query_embedding vector(384),
	match_threshold float default 0.3,
	match_count int default 20,
	from_ts timestamptz default now() - interval '7 days'
)
returns table (
	packet_id uuid,
	timestamp timestamptz,
	src_ip inet,
	dst_ip inet,
	protocol varchar,
	is_malicious boolean,
	similarity float
)
language sql
as $$
	select
		p.id as packet_id,
		p.timestamp,
		p.src_ip,
		p.dst_ip,
		p.protocol,
		p.is_malicious,
		1 - (e.embedding <=> query_embedding) as similarity
	from public.network_packet_embeddings e
	join public.network_packets p on p.id = e.packet_id
	where p.timestamp >= from_ts
	  and e.embedding is not null
	  and (1 - (e.embedding <=> query_embedding)) >= match_threshold
	order by e.embedding <=> query_embedding
	limit match_count;
$$;
```

### Llamada desde `supabase-py` (patrón actual)

```python
response = client.rpc(
	"search_similar_network_packets",
	{
		"query_embedding": embedding_384,
		"match_threshold": 0.3,
		"match_count": 20,
	},
).execute()
results = response.data or []
```

### Llamada desde `supabase-js`

```ts
const { data, error } = await supabase.rpc('search_similar_network_packets', {
	query_embedding: embedding384,
	match_threshold: 0.3,
	match_count: 20,
})
```

---

## InfluxDB: qué sí enviar

Solo agregados por ventana (5s/30s), por ejemplo:

- measurement: `net_window_metrics`
- tags: `sensor_id`, `iface`, `protocol`
- fields: `packets`, `bytes`, `flows`, `malicious_count`, `dns_nx`, `anomaly_score`

No enviar payload crudo a InfluxDB.

---

## Pipeline recomendado final

1. `tshark` captura y rota PCAP.
2. Parser extrae features/eventos.
3. Insert en `network_packets`.
4. Construir `text_content` y generar embedding (384).
5. Upsert en `network_packet_embeddings`.
6. Escribir métricas agregadas a InfluxDB.
7. Usar RPC `search_similar_network_packets` para top-k.

---

## Validaciones SQL rápidas

```sql
-- Ver dimensiones presentes
select vector_dims(embedding) as dims, count(*)
from public.network_packet_embeddings
where embedding is not null
group by 1;

-- Ver cuántos eventos tienen embedding
select
	count(*) as total_packets,
	count(e.packet_id) as packets_with_embedding
from public.network_packets p
left join public.network_packet_embeddings e on e.packet_id = p.id;
```

---

## Seguridad (pendiente obligatoria)

- Mover credenciales a `.env` (no dejar secretos en markdown/repo).
- Rotar claves que hayan quedado expuestas.
- Usar service key solo en backend.

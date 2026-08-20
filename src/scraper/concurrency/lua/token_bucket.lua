-- KEYS[1]: bucket key
-- KEYS[2]: manifest expiry key (optional)
-- ARGV[1]: capacity
-- ARGV[2]: refill rate (tokens per second)
-- ARGV[3]: requested tokens
-- ARGV[4]: current time (seconds from Redis TIME)

local bucket_key = KEYS[1]
local expiry_key = KEYS[2]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

-- Check manifest expiry if key exists
local expiry_ts_str = redis.call("GET", expiry_key)
if expiry_ts_str then
    local expiry_ts = tonumber(expiry_ts_str)
    if expiry_ts and now > expiry_ts then
        -- Return sentinel for expired manifest {allowed, remaining, wait_seconds}
        return {0, 0, -1}
    end
end

-- Token bucket logic
local last_tokens = capacity
local last_refreshed = now

local bucket_data = redis.call("HMGET", bucket_key, "tokens", "last_refreshed")
if bucket_data[1] and bucket_data[2] then
    last_tokens = tonumber(bucket_data[1])
    last_refreshed = tonumber(bucket_data[2])
end

local time_passed = math.max(0, now - last_refreshed)
local new_tokens = math.min(capacity, last_tokens + time_passed * refill_rate)

local allowed = 0
local wait_seconds = 0

if new_tokens >= requested then
    allowed = 1
    new_tokens = new_tokens - requested
else
    wait_seconds = (requested - new_tokens) / refill_rate
end

redis.call("HMSET", bucket_key, "tokens", new_tokens, "last_refreshed", now)
-- Set TTL to clean up unused buckets (capacity / refill_rate + buffer)
local ttl = math.ceil(capacity / refill_rate) + 60
redis.call("EXPIRE", bucket_key, ttl)

return {allowed, new_tokens, wait_seconds}

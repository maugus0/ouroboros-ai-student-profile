"""Security utilities (legacy support removed; use internal bearer tokens).

Legacy X-Service-Token validation has been removed.
All inter-service communication now uses Kubernetes-native internal bearer tokens.
See app/middleware/service_auth.py for internal token verification.
"""

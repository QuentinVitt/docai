define log_info
	@echo "[INFO] $(1)"
endef

define log_success
	@echo "[OK] $(1)"
endef

define require_var
	$(if $($(1)),,$(error Variable $(1) is required))
endef

check-clean:
	@git diff --exit-code || (echo "Uncommitted changes" && exit 1)

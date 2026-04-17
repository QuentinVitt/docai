include config.mk
include scripts/helpers.mk

.DEFAULT_GOAL := all
.PHONY: all build test lint clean install dev docs

# Directories
SRC_DIR := src
BUILD_DIR := build
DIST_DIR := dist
TEST_DIR := tests
DOCS_DIR := docs

# Compiler settings
CC := gcc
CFLAGS := -Wall -Wextra -O2 -std=c11
LDFLAGS := -lm

# Source files
SOURCES := $(wildcard $(SRC_DIR)/**/*.c $(SRC_DIR)/*.c)
OBJECTS := $(SOURCES:$(SRC_DIR)/%.c=$(BUILD_DIR)/%.o)
TARGET := $(DIST_DIR)/app

all: build

build: $(TARGET)

$(TARGET): $(OBJECTS)
	@mkdir -p $(DIST_DIR)
	$(CC) $(LDFLAGS) -o $@ $^

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c -o $@ $<

test: build
	@echo "Running tests..."
	uv run pytest $(TEST_DIR) -v

lint:
	ruff check $(SRC_DIR)
	mypy $(SRC_DIR)

clean:
	rm -rf $(BUILD_DIR) $(DIST_DIR)

install: build
	install -d $(DESTDIR)/usr/local/bin
	install -m 755 $(TARGET) $(DESTDIR)/usr/local/bin/

dev:
	uv run python -m $(SRC_DIR).main --reload

docs:
	mkdocs build -f $(DOCS_DIR)/mkdocs.yml

#!/usr/bin/env Rscript

usage <- function() {
  cat(
    paste(
      "Usage: Rscript scripts/export_farr_support_data.R [options]",
      "",
      "Export farr support datasets used by reporting-risk-cascade diagnostics:",
      "  - farr::aaer_dates",
      "  - farr::aaer_firm_year",
      "  - farr::state_hq",
      "",
      "Options:",
      "  --out-dir PATH          Output directory.",
      "                          Default: DATA_DIR/external",
      "  --source-version TEXT   Override source_version column.",
      "                          Default: farr <installed-version>",
      "  --install-missing       Install farr from CRAN if it is not installed.",
      "  --repos URL             CRAN repo for --install-missing.",
      "                          Default: https://cloud.r-project.org",
      "  --help                  Show this message.",
      sep = "\n"
    )
  )
}

parse_args <- function(args) {
  data_dir <- Sys.getenv("DATA_DIR", unset = "data")
  if (!nzchar(data_dir)) {
    data_dir <- "data"
  }
  opts <- list(
    out_dir = file.path(data_dir, "external"),
    source_version = "",
    install_missing = FALSE,
    repos = "https://cloud.r-project.org"
  )

  i <- 1
  while (i <= length(args)) {
    arg <- args[[i]]
    if (arg == "--help" || arg == "-h") {
      usage()
      quit(status = 0)
    } else if (arg == "--install-missing") {
      opts$install_missing <- TRUE
      i <- i + 1
    } else if (arg %in% c("--out-dir", "--source-version", "--repos")) {
      if (i == length(args)) {
        stop(sprintf("%s requires a value", arg), call. = FALSE)
      }
      value <- args[[i + 1]]
      if (arg == "--out-dir") {
        opts$out_dir <- value
      } else if (arg == "--source-version") {
        opts$source_version <- value
      } else if (arg == "--repos") {
        opts$repos <- value
      }
      i <- i + 2
    } else {
      stop(sprintf("Unknown option: %s", arg), call. = FALSE)
    }
  }
  opts
}

normalize_text <- function(x) {
  out <- iconv(as.character(x), from = "latin1", to = "UTF-8", sub = "")
  out[out %in% c("NA", "NaN", "NULL", "Inf", "-Inf", "")] <- NA_character_
  out
}

coerce_date <- function(x) {
  if (inherits(x, "Date")) {
    return(x)
  }
  if (inherits(x, "POSIXt")) {
    return(as.Date(x))
  }
  if (is.numeric(x)) {
    return(as.Date(x, origin = "1970-01-01"))
  }
  as.Date(as.character(x))
}

write_export <- function(frame, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  write.csv(frame, path, row.names = FALSE, na = "", fileEncoding = "UTF-8")
  cat(sprintf("Wrote %d rows to %s\n", nrow(frame), path))
}

opts <- parse_args(commandArgs(trailingOnly = TRUE))

if (!requireNamespace("farr", quietly = TRUE)) {
  if (isTRUE(opts$install_missing)) {
    install.packages("farr", repos = opts$repos)
  } else {
    stop(
      paste(
        "The R package 'farr' is not installed.",
        "Run install.packages('farr') or pass --install-missing."
      ),
      call. = FALSE
    )
  }
}

source_version <- opts$source_version
if (!nzchar(source_version)) {
  source_version <- paste0("farr ", as.character(utils::packageVersion("farr")))
}
extracted_at <- format(as.POSIXct(Sys.time(), tz = "UTC"), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")

data("aaer_dates", package = "farr", envir = environment())
data("aaer_firm_year", package = "farr", envir = environment())
data("state_hq", package = "farr", envir = environment())

aaer_dates_raw <- get("aaer_dates")
aaer_dates_out <- data.frame(
  aaer_num = normalize_text(aaer_dates_raw$aaer_num),
  aaer_date = as.character(coerce_date(aaer_dates_raw$aaer_date)),
  aaer_desc = normalize_text(aaer_dates_raw$aaer_desc),
  year = as.integer(aaer_dates_raw$year),
  source = "farr_aaer_dates",
  source_version = source_version,
  extracted_at = extracted_at,
  stringsAsFactors = FALSE
)
aaer_dates_out <- unique(aaer_dates_out[!is.na(aaer_dates_out$aaer_num), , drop = FALSE])

aaer_firm_year_raw <- get("aaer_firm_year")
aaer_firm_year_out <- data.frame(
  p_aaer = normalize_text(aaer_firm_year_raw$p_aaer),
  gvkey = normalize_text(aaer_firm_year_raw$gvkey),
  min_year = as.integer(aaer_firm_year_raw$min_year),
  max_year = as.integer(aaer_firm_year_raw$max_year),
  source = "farr_aaer_firm_year",
  source_version = source_version,
  extracted_at = extracted_at,
  stringsAsFactors = FALSE
)
aaer_firm_year_out <- unique(
  aaer_firm_year_out[
    !is.na(aaer_firm_year_out$p_aaer) &
      !is.na(aaer_firm_year_out$gvkey) &
      !is.na(aaer_firm_year_out$min_year) &
      !is.na(aaer_firm_year_out$max_year) &
      aaer_firm_year_out$max_year >= aaer_firm_year_out$min_year,
    ,
    drop = FALSE
  ]
)

state_hq_raw <- get("state_hq")
state_hq_out <- data.frame(
  issuer_cik = normalize_text(state_hq_raw$cik),
  ba_state = normalize_text(state_hq_raw$ba_state),
  min_date = as.character(coerce_date(state_hq_raw$min_date)),
  max_date = as.character(coerce_date(state_hq_raw$max_date)),
  source = "farr_state_hq",
  source_version = source_version,
  extracted_at = extracted_at,
  match_method = "farr_state_hq_date_range",
  stringsAsFactors = FALSE
)
state_hq_out <- unique(
  state_hq_out[
    !is.na(state_hq_out$issuer_cik) &
      !is.na(state_hq_out$ba_state) &
      !is.na(state_hq_out$min_date),
    ,
    drop = FALSE
  ]
)

write_export(aaer_dates_out, file.path(opts$out_dir, "farr_aaer_dates.csv"))
write_export(aaer_firm_year_out, file.path(opts$out_dir, "farr_aaer_firm_year.csv"))
write_export(state_hq_out, file.path(opts$out_dir, "farr_state_hq.csv"))
cat(sprintf("Source version: %s\n", source_version))

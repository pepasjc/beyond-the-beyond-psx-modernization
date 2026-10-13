/* meta.h: achievement texts and points (gen/set.c) */
#pragma once
#include <stdint.h>

extern const uint16_t ra_total_points;
extern const uint8_t ra_points[];
/* per achievement: title, description (lines split by '\n'); bytes 0x80.. stand for
   entry (byte - 0x80) of the phrase dictionary */
extern const uint16_t ra_text_off[], ra_dict_off[];
extern const uint8_t ra_text[];
extern const char ra_dict[];
#define RA_TITLE(i) (ra_text + ra_text_off[(i) * 2])
#define RA_DESC(i)  (ra_text + ra_text_off[(i) * 2 + 1])
